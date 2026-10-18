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