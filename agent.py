import json
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from llm import chat
from sessions import load_session, save_session
from tools.base import Tool
from tools.registry import ToolRegistry


def run_agent(
    registry: ToolRegistry,
    base_tools: list[Tool],
    load_qgis_tool: Callable[[str], Tool],
    output_root: Path,
) -> None:
    session_id = input("Session: ").strip()
    messages = load_session(session_id)

    output_dir = (
        output_root / uuid4().hex
    ).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    instructions = f"""
你是 GIS 助手，可以发现并调用 QGIS Processing 工具。

需要 GIS 运算能力时，先调用 search_qgis_tools。
将中文任务转换成简短英文关键词。
复杂任务可以按步骤分别搜索，例如：
reproject layer、vector buffer、polygon intersection。

搜索结果中的 tool_name 是实际可调用的函数名。
这些具体工具的参数定义会在下一轮提供。
获得参数定义后，再调用具体工具。
没有找到合适工具时，调整关键词重新搜索。

只使用用户提供的输入数据路径，不要编造文件路径。
缺少输入路径、必要字段或关键数据信息时，向用户询问。
没有明确输出位置时，把结果保存到：{output_dir}
中间结果也保存到文件，后续步骤使用工具实际返回的路径。
不要使用 memory: 或 TEMPORARY_OUTPUT。

米制缓冲需要合适的米制投影，不能把经纬度单位当作米。
根据用户指定的 CRS 和数据情况决定是否重投影。

工具失败时，阅读错误并修正参数，或者向用户说明问题。
检查工具返回的日志，不要忽略错误和警告。
只有工具实际成功后，才能告诉用户已经完成。
""".strip()

    print(f"Output directory: {output_dir}")

    while True:
        user_input = input("You: ").strip()

        if user_input == "exit":
            break

        messages.append(
            {
                "role": "user",
                "content": user_input,
            }
        )

        available_tools = {
            tool.name: tool
            for tool in base_tools
        }

        for _ in range(12):
            message = chat(
                [
                    {
                        "role": "system",
                        "content": instructions,
                    },
                    *messages,
                ],
                list(available_tools.values()),
            )

            assistant_message = {
                "role": "assistant",
                "content": message.content,
            }

            if message.tool_calls:
                assistant_message["tool_calls"] = [
                    tool_call.model_dump()
                    for tool_call in message.tool_calls
                ]

            messages.append(assistant_message)

            if not message.tool_calls:
                print("Agent:", message.content)
                break

            for tool_call in message.tool_calls:
                name = tool_call.function.name
                arguments = json.loads(
                    tool_call.function.arguments
                )

                print("Tool called:", name)
                print("Tool arguments:", arguments)

                if name not in available_tools:
                    result = {
                        "ok": False,
                        "error": (
                            f"工具 {name} 尚未提供。"
                            "请先通过 search_qgis_tools 发现它。"
                        ),
                    }
                else:
                    result = registry.execute(
                        name,
                        arguments,
                    )

                    if name == "search_qgis_tools":
                        for item in result:
                            tool = load_qgis_tool(
                                item["algorithm_id"]
                            )
                            available_tools[tool.name] = tool
                            item["tool_name"] = tool.name

                print("Tool result:", result)

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(
                            result,
                            ensure_ascii=False,
                        ),
                    }
                )

            save_session(session_id, messages)

        else:
            notice = (
                "本轮达到工具调用轮数上限，已停止。"
                "已有工具结果和输出文件已保留。"
            )
            print("Agent:", notice)
            messages.append(
                {
                    "role": "assistant",
                    "content": notice,
                }
            )

        save_session(session_id, messages)