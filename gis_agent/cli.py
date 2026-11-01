import logging
import json
import os
from pathlib import Path
from typing import Annotated
from uuid import uuid4

import typer
from dotenv import dotenv_values

from gis_agent.persistence.executions import ExecutionHistory
from gis_agent.persistence.sessions import SessionStore


app = typer.Typer(add_completion=False)


def chat(
    project: Annotated[Path, typer.Option(help='项目目录，也是默认记录目录。')] = Path(__file__).resolve().parents[1],
    session: Annotated[str | None, typer.Option(help='会话 ID；不填时交互输入。')] = None,
) -> None:
    from gis_agent.application import open_conversation
    from gis_agent.config import AppConfig

    logging.basicConfig(level=logging.INFO, format='%(message)s')
    config = AppConfig.from_env(project)
    session_id = session or typer.prompt('Session（留空新建）', default='', show_default=False) or uuid4().hex
    with open_conversation(config, session_id) as conversation:
        typer.echo(f'Session: {session_id}\n输出目录: {conversation.output_dir}')
        if conversation.pending:
            result = conversation.resume()
            typer.echo(f"Status: {result['status']}\nAgent: {result['summary']}")
        while True:
            text = typer.prompt('You').strip()
            if text == 'exit':
                break
            if text:
                result = conversation.send(text)
                typer.echo(f"Status: {result['status']}\nAgent: {result['summary']}")


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    project: Annotated[Path, typer.Option(help="项目目录。 ")] = Path(__file__).resolve().parents[1],
    session: Annotated[str | None, typer.Option(help="会话 ID。 ")] = None,
) -> None:
    ctx.obj = {"project": project, "session": session}
    if ctx.invoked_subcommand is None:
        chat(project, session)


@app.command("chat")
def chat_command(
    ctx: typer.Context,
    project: Annotated[Path | None, typer.Option()] = None,
    session: Annotated[str | None, typer.Option()] = None,
) -> None:
    chat(project or ctx.obj["project"], session or ctx.obj["session"])


@app.command()
def history(
    ctx: typer.Context,
    session: Annotated[str | None, typer.Option()] = None,
    project: Annotated[Path | None, typer.Option()] = None,
    output_dir: Annotated[Path | None, typer.Option(help="归档会话的实际成果目录；默认沿用项目配置。 ")] = None,
    execution: Annotated[str | None, typer.Option()] = None,
    query: Annotated[str | None, typer.Option()] = None,
    tool: Annotated[str | None, typer.Option()] = None,
    status: Annotated[str | None, typer.Option()] = None,
    section: Annotated[str, typer.Option()] = "summary",
    offset: Annotated[int, typer.Option()] = 0,
    limit: Annotated[int, typer.Option()] = 5,
    cursor: Annotated[int, typer.Option()] = 0,
    max_characters: Annotated[int, typer.Option()] = 4000,
) -> None:
    project = (project or ctx.obj["project"]).expanduser().resolve()
    session = session or ctx.obj["session"]
    if not session:
        raise typer.BadParameter("请提供 --session。")
    settings = dotenv_values(project / ".env")
    def directory(key: str, default: Path) -> Path:
        value = Path(os.environ.get(key) or settings.get(key) or default).expanduser()
        return (value if value.is_absolute() else project / value).resolve()
    try:
        store = SessionStore(directory("GIS_AGENT_SESSIONS_DIR", project / "sessions"), session)
        reader = ExecutionHistory(store, output_dir or directory("GIS_AGENT_OUTPUTS_DIR", project / "outputs") / session)
        result = reader.query(execution_id=execution, query=query, tool=tool, status=status, section=section,
                              offset=offset, limit=limit, cursor=cursor, max_characters=max_characters)
    except (OSError, ValueError) as error:
        result = {"ok": False, "error": str(error)}
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ok"]:
        raise typer.Exit(1)
