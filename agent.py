import json
from collections.abc import Callable
from dataclasses import dataclass
from itertools import count
from pathlib import Path
from typing import Any
from uuid import uuid4

from context import ContextConfig, ContextLimit, ContextManager
from llm import AuxiliaryCalls, AuxiliaryError, ModelReply, TokenCounter
from memory import MemoryConfig, MemoryStore, MemoryTurn, extract_memories
from planning import Plan
from sessions import SessionStore, message_units
from tools.base import Tool
from tools.memory import make_memory_tools
from tools.planning import make_planning_tools
from tools.registry import ToolRegistry
from tools.session import make_session_tool


REVIEW_INSTRUCTIONS = """
交付前，对照用户原始要求及后续澄清逐项复核，不只检查你自己的计划。
若要求已进入摘要，用 read_session_messages 按来源回读当前任务的原话及澄清。
核对实际产物、证据、遗漏和格式偏差。需要事实依据时继续调用工具。
发现问题就修正并重新检查；不能验证的内容如实说明。
更新计划后，单独调用 finish_task 报告 completed、needs_input 或 blocked。
""".strip()


@dataclass
class Agent:
    registry: ToolRegistry
    base_tools: list[Tool]
    load_qgis_tool: Callable[[str], Tool]
    plan: Plan
    instructions: str
    chat: Callable[..., ModelReply]
    store: SessionStore
    context: ContextManager
    memory: MemoryStore | None = None
    memory_turn: MemoryTurn | None = None

    def finish(self, messages: list[dict[str, Any]], outcome: dict[str, Any]) -> dict[str, Any]:
        messages.append({"role": "assistant", "content": outcome["summary"]})
        self.store.save(messages)
        if self.memory is not None and outcome['status'] in {'answer', 'completed'}:
            try:
                maintenance = extract_memories(self.memory, self.store, messages, self.memory_turn, self.context.auxiliary)
            except (OSError, ValueError, KeyError, TypeError) as error:
                maintenance = {'status': 'failed', 'error': str(error)}
            outcome = {**outcome, 'memory': maintenance}
            self.store.record_model_call({'purpose': 'memory_maintenance', **maintenance})
            print('Memory:', maintenance)
        return outcome

    def run(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        message_units(messages)
        self.context.auxiliary.reset()
        if self.memory_turn is not None:
            self.memory_turn.reset(len(messages) - 1)
        memory_errors: set[str] = set()
        background = ''
        if self.memory is not None:
            query = messages[self.memory_turn.start]['content'] + ' ' + self.plan.goal
            background = json.dumps(self.memory.recall(query), ensure_ascii=False)
        available = {tool.name: tool for tool in self.base_tools}
        review_started = False
        execution_started = False
        self.store.save(messages)

        for step in count():
            state = {
                "plan": self.plan.snapshot(), "review_started": review_started,
                "execution_started": execution_started, "responses_used": step,
                "latest_user_message": max(i for i, item in enumerate(messages) if item['role'] == 'user' and item.get('origin') != 'program'),
                "recent_tool_messages": {item['tool_call_id']: i for i, item in enumerate(messages) if item['role'] == 'tool' and i >= len(messages) - 20},
            }
            try:
                request = self.context.prepare(self.instructions, messages, state, list(available.values()), background)
            except (ContextLimit, AuxiliaryError) as error:
                return self.finish(messages, {"ok": False, "status": "blocked", "summary": str(error)})
            reply = self.chat(request.messages, request.schemas)
            self.store.record_model_call({"purpose": "main", **reply.metadata()})
            print("Model:", reply.metadata(), "Estimated request tokens:", request.estimated_tokens)
            if reply.finish_reason not in {"stop", "tool_calls"}:
                messages.append({
                    "role": "assistant", "content": "模型响应未完整结束，未执行其中的工具调用。",
                    "response": {**reply.metadata(), "raw_message": reply.message},
                })
                return self.finish(messages, {
                    "ok": False, "status": "blocked",
                    "summary": f"模型结束状态为 {reply.finish_reason}，请检查输出预算。",
                })

            message = {**reply.message, "response": reply.metadata()}
            if not message.get("tool_calls"):
                message.pop("tool_calls", None)
            messages.append(message)
            self.store.save(messages)
            calls = message.get("tool_calls", [])
            if not calls:
                messages.append({
                    "role": "user", "origin": "program",
                    "content": "请单独调用 finish_task 报告状态；若仍有工作则继续调用工具。",
                })
                self.store.save(messages)
                continue

            outcome = None
            for call in calls:
                name = call["function"]["name"]
                arguments = None
                try:
                    arguments = json.loads(call["function"]["arguments"])
                except json.JSONDecodeError as error:
                    result = {"ok": False, "error": f"工具参数不是有效 JSON：{error}"}
                else:
                    if not isinstance(arguments, dict):
                        result = {"ok": False, "error": "工具参数必须是 JSON 对象。"}
                    elif name not in request.callable_names:
                        result = {"ok": False, "error": f"本次没有提供工具 {name}，请先搜索。"}
                    elif name == "finish_task" and len(calls) != 1:
                        result = {"ok": False, "error": "finish_task 必须单独调用。"}
                    else:
                        if name not in {"update_plan", "finish_task", "read_session_messages", "search_memory", "remember_memory", "forget_memory"}:
                            execution_started = True
                        result = self.registry.execute(name, arguments)
                        if name == "search_qgis_tools":
                            for item in result:
                                tool = self.load_qgis_tool(item["algorithm_id"])
                                available.pop(tool.name, None)
                                available[tool.name] = tool
                                item["tool_name"] = tool.name
                        if name == "finish_task" and result["ok"]:
                            status = result["status"]
                            if memory_errors and status in {'answer', 'completed'}:
                                result = {'ok': False, 'error': '记忆操作仍有失败项，请重试对应操作或报告 blocked。'}
                            elif status == "answer" and execution_started:
                                result = {"ok": False, "error": "本轮已执行操作，请报告任务状态。"}
                            elif status == "completed" and not review_started:
                                review_started = True
                                result = {
                                    **result, "status": "review_required", "instruction": REVIEW_INSTRUCTIONS,
                                    "unfinished": self.plan.unfinished(),
                                }
                            elif status == "completed" and self.plan.unfinished():
                                result = {
                                    "ok": False, "error": "计划仍有未完成项，请继续处理或报告阻碍。",
                                    "unfinished": self.plan.unfinished(),
                                }
                            else:
                                outcome = result

                if name in {'remember_memory', 'forget_memory'}:
                    if result.get('ok'):
                        memory_errors.discard(name)
                        if self.memory is not None:
                            background = json.dumps(self.memory.recall(query), ensure_ascii=False)
                    else:
                        memory_errors.add(name)
                stored = self.store.tool_message(call["id"], name, result, self.context.config.tool_limit)
                messages.append(stored)
                self.store.save(messages)
                print("Tool:", name, "Result:", stored["content"][:1200])

            if outcome is not None:
                return self.finish(messages, outcome)

def run_agent(
    registry: ToolRegistry, base_tools: list[Tool], load_qgis_tool: Callable[[str], Tool],
    output_root: Path, *, chat: Callable[..., ModelReply], session_root: Path,
    context_config: ContextConfig, count_tokens: TokenCounter,
    memory_config: MemoryConfig | None = None,
) -> None:
    session_id = input("Session（留空新建）: ").strip() or uuid4().hex
    store = SessionStore(session_root, session_id)
    messages = store.load()
    plan = Plan.from_messages(messages)
    planning_tools = make_planning_tools(plan)
    for tool in planning_tools:
        registry.register(tool)
    session_tool = make_session_tool(store)
    registry.register(session_tool)
    active_base = [*base_tools, *planning_tools, session_tool]
    memory = MemoryStore(memory_config) if memory_config is not None else None
    memory_turn = MemoryTurn() if memory is not None else None
    if memory is not None:
        memory_tools = make_memory_tools(memory, store, messages, memory_turn)
        for tool in memory_tools:
            registry.register(tool)
        active_base.extend(memory_tools)
    output_dir = (output_root / uuid4().hex).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    instructions = f"""
你是 GIS 助手，可以检查数据、调用 QGIS 工具，也可以编写和执行 Python 脚本。

需要文件和数据信息时，使用 list_files、read_file 和 inspect_data。
需要历史偏好或经验时可用 search_memory。用户明确要求记住、纠正或删除时，调用对应记忆工具并检查结果。
记忆是带来源与适用范围的背景，当前要求和当前检查结果优先；临时要求不转成长期默认。
remember_memory 的 source_indices 使用状态中的 latest_user_message、recent_tool_messages 或回读得到的消息序号。
先检查字段、CRS 和单位；无法从数据判定的关键业务含义再询问用户。

需要 QGIS 算法时，先用 search_qgis_tools 搜索简短英文关键词。
搜索结果的 tool_name 是候选函数名，本次可调用项以实际提供的 schema 为准。
需要被移出候选的算法时，按完整算法 ID 再次搜索。
没有找到合适工具时，调整关键词。

需要自定义分析或制图时，用 write_file 保存 .py 脚本，再调用 run_python_script。
脚本使用 QGIS 自带 Python，不会自动初始化 PyQGIS 或 Processing。
使用 PyQGIS 时，创建 QgsApplication([], False) 并调用 initQgis()，最后调用 exitQgis()。
使用 Processing 时，将 QgsApplication.prefixPath() 下的 python/plugins 加入 sys.path，
再导入 processing.core.Processing 中的 Processing，调用 Processing.initialize()。
不要自行安装依赖，不要通过高级 Python 字段计算器绕道执行整段程序。

只使用用户提供或通过工具发现的输入路径，不修改原始输入或项目源码。
没有指定输出位置时，结果保存到：{output_dir}
脚本保存在该目录的 scripts 子目录。输入和输出使用绝对路径。
修改本轮自己的脚本或报告时，write_file 可传 overwrite=true。
不同脚本进程不共享变量；跨进程中间成果落盘，不使用 memory: 或 TEMPORARY_OUTPUT。

米制运算使用合适的米制投影，不把经纬度单位当作米。
脚本打印实际产物路径。失败时阅读 stderr，必要时用 read_file 分段读取完整日志。
正常退出不等于业务正确；只报告实际结果和已知限制，不编造成功。

多步骤执行任务先调用 update_plan，最后包含按用户要求复核并整理交付。
继续同一任务时保留已完成项；用户明确换任务时替换目标和清单。
普通问答或仅讨论计划无需执行分析，不要清除已有未完成任务。
继续任务时复用会话中已有产物的实际路径，不要因本次输出目录不同就重新计算。

每轮结束都要单独调用 finish_task，不与其他工具放在同一条响应中。
普通问答或仅提供计划使用 answer；需要用户补充信息使用 needs_input；执行受阻使用 blocked。
执行任务完成时使用 completed 请求交付，summary 写实际成果、证据路径和已知限制。
首次 completed 会返回 review_required，要求你对照用户原始要求及澄清复核。
此时继续使用工具检查或修正，更新计划，再次调用 finish_task 报告最终状态。
不得为了通过流程而把未完成项改成已完成，也不要凭空增加用户没有要求的目标。

""".strip()
    agent = Agent(
        registry=registry, base_tools=active_base,
        load_qgis_tool=load_qgis_tool, plan=plan, instructions=instructions,
        chat=chat, store=store, context=ContextManager(
            store, context_config,
            AuxiliaryCalls(
                chat=chat,
                record=store.record_model_call,
                count_tokens=count_tokens,
                token_limit=context_config.request_token_limit,
            ),
            {tool.name for tool in active_base},
        ), memory=memory, memory_turn=memory_turn,
    )
    print("Session:", session_id, "Output directory:", output_dir)
    while True:
        user_input = input("You: ").strip()
        if user_input == "exit":
            break
        if not user_input:
            continue
        messages.append({"role": "user", "origin": "user", "content": user_input})
        result = agent.run(messages)
        print("Status:", result["status"])
        print("Agent:", result["summary"])
