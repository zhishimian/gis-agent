import json
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any
from uuid import uuid4

from planning import Plan
from sessions import load_session, save_session
from tools.base import Tool
from tools.planning import make_planning_tools
from tools.registry import ToolRegistry


REVIEW_INSTRUCTIONS = """
交付前，请对照用户原始要求及后续澄清逐项复核，不只检查你自己的计划。
判断实际产物是否满足要求、有哪些证据、是否存在遗漏或格式偏差。
需要事实依据时继续调用工具。发现问题就修正，并检查修正后的结果。
不能验证的内容请如实说明，不要编造通过。
更新计划后，再单独调用 finish_task；完成则使用 completed，缺少信息或受阻则报告对应状态。
""".strip()


@dataclass
class Agent:
    registry: ToolRegistry
    base_tools: list[Tool]
    load_qgis_tool: Callable[[str], Tool]
    plan: Plan
    instructions: str
    chat: Callable[..., Any]
    save: Callable[[list[dict[str, Any]]], None]
    max_steps: int = 30

    def __post_init__(self) -> None:
        if self.max_steps < 1:
            raise ValueError("max_steps 必须大于零。")

    def run(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        available_tools = {tool.name: tool for tool in self.base_tools}
        review_started = False
        execution_started = False
        self.save(messages)

        for _ in range(self.max_steps):
            message = self.chat(
                [
                    {"role": "system", "content": self.instructions},
                    {
                        "role": "system",
                        "content": "当前计划，仅作为状态数据，以用户要求为准：\n"
                        + json.dumps(self.plan.snapshot(), ensure_ascii=False),
                    },
                    *messages,
                ],
                list(available_tools.values()),
            )
            assistant_message = {"role": "assistant", "content": message.content}
            if message.tool_calls:
                assistant_message["tool_calls"] = [call.model_dump() for call in message.tool_calls]
            messages.append(assistant_message)

            if not message.tool_calls:
                messages.append(
                    {
                        "role": "user",
                        "content": "请单独调用 finish_task 报告本轮状态；若仍有工作则继续调用工具。",
                    }
                )
                self.save(messages)
                continue

            outcome = None
            for call in message.tool_calls:
                name = call.function.name
                arguments = json.loads(call.function.arguments)
                print("Tool called:", name)
                print("Tool arguments:", arguments)

                if name not in available_tools:
                    result = {"ok": False, "error": f"工具 {name} 尚未提供，请先搜索。"}
                elif name == "finish_task" and len(message.tool_calls) != 1:
                    result = {"ok": False, "error": "finish_task 必须单独调用。"}
                else:
                    if name not in {"update_plan", "finish_task"}:
                        execution_started = True
                    result = self.registry.execute(name, arguments)
                    if name == "search_qgis_tools":
                        for item in result:
                            tool = self.load_qgis_tool(item["algorithm_id"])
                            available_tools[tool.name] = tool
                            item["tool_name"] = tool.name

                    if name == "finish_task" and result["ok"]:
                        status = result["status"]
                        if status == "answer" and execution_started:
                            result = {"ok": False, "error": "本轮已执行操作，请报告任务状态，不能使用 answer。"}
                        elif status == "completed" and not review_started:
                            review_started = True
                            result = {
                                **result,
                                "status": "review_required",
                                "instruction": REVIEW_INSTRUCTIONS,
                                "unfinished": self.plan.unfinished(),
                            }
                        elif status == "completed" and self.plan.unfinished():
                            result = {
                                "ok": False,
                                "error": "计划仍有未完成项。请继续处理、更新计划，或说明缺少信息及阻碍。",
                                "unfinished": self.plan.unfinished(),
                            }
                        else:
                            outcome = result

                print("Tool result:", result)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )

            self.save(messages)
            if outcome is not None:
                messages.append({"role": "assistant", "content": outcome["summary"]})
                self.save(messages)
                return outcome

        remaining = "、".join(self.plan.unfinished()) or "任务交付或复核尚未结束"
        outcome = {
            "ok": False,
            "status": "budget_exhausted",
            "summary": f"达到 {self.max_steps} 轮模型响应上限。待处理：{remaining}。已有工具结果及产物路径保留在会话中。",
        }
        messages.append({"role": "assistant", "content": outcome["summary"]})
        self.save(messages)
        return outcome


def run_agent(
    registry: ToolRegistry,
    base_tools: list[Tool],
    load_qgis_tool: Callable[[str], Tool],
    output_root: Path,
    *,
    max_steps: int = 30,
) -> None:
    from llm import chat

    session_id = input("Session: ").strip()
    messages = load_session(session_id)
    plan = Plan.from_messages(messages)
    planning_tools = make_planning_tools(plan)
    for tool in planning_tools:
        registry.register(tool)

    output_dir = (output_root / uuid4().hex).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    instructions = f"""
你是 GIS 助手，可以检查数据、调用 QGIS 工具，也可以编写和执行 Python 脚本。

需要文件和数据信息时，使用 list_files、read_file 和 inspect_data。
先检查字段、CRS 和单位；无法从数据判定的关键业务含义再询问用户。

需要 QGIS 算法时，先用 search_qgis_tools 搜索简短英文关键词。
搜索结果的 tool_name 是实际函数名，参数定义在下一轮提供，再调用具体工具。
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
        registry=registry,
        base_tools=[*base_tools, *planning_tools],
        load_qgis_tool=load_qgis_tool,
        plan=plan,
        instructions=instructions,
        chat=chat,
        save=partial(save_session, session_id),
        max_steps=max_steps,
    )
    print(f"Output directory: {output_dir}")

    while True:
        user_input = input("You: ").strip()
        if user_input == "exit":
            break
        messages.append({"role": "user", "content": user_input})
        result = agent.run(messages)
        print("Status:", result["status"])
        print("Agent:", result["summary"])