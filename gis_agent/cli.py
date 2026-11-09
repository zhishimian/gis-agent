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


def show_result(result):
    typer.echo(f"Status: {result['status']}\nAgent: {result['summary']}")
    if result['status'] == 'needs_input':
        typer.echo('需要补充：' + result.get('question', result['summary']))
        if result.get('unresolved'):
            typer.echo('尚未完成：' + '；'.join(result['unresolved']))
        if result.get('artifacts'):
            typer.echo('已保留：' + '；'.join(result['artifacts']))
        typer.echo('输入补充内容继续；exit保存退出；cancel取消任务。')


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
            show_result(result)
        elif conversation.pending_answer:
            show_result(conversation.continue_answer())
        elif conversation.waiting:
            show_result(conversation.waiting)
        while True:
            try:
                text = typer.prompt('补充' if conversation.waiting else 'You').strip()
            except (EOFError, KeyboardInterrupt, typer.Abort):
                typer.echo('记录已保留。')
                break
            if text == 'exit':
                break
            if text == 'cancel':
                try:
                    show_result(conversation.cancel())
                except ValueError as error:
                    typer.echo(str(error))
                continue
            if text:
                try:
                    show_result(conversation.send(text))
                except ValueError as error:
                    typer.echo(str(error))


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


@app.command('waiting')
def waiting_command(ctx: typer.Context, session: Annotated[str | None, typer.Option()] = None) -> None:
    """只读查看等待，无需模型Key或QGIS启动。"""
    from gis_agent.persistence.interaction import latest_outcome
    project = ctx.obj['project'].resolve()
    session = session or ctx.obj['session']
    if not session:
        raise typer.BadParameter('请提供--session。')
    settings = dotenv_values(project / '.env')
    root = Path(os.environ.get('GIS_AGENT_SESSIONS_DIR') or settings.get('GIS_AGENT_SESSIONS_DIR') or project/'sessions')
    if not root.is_absolute():
        root = project/root
    store = SessionStore(root.resolve(),session)
    try:
        result = latest_outcome(store,store.read_record())
    except (OSError, ValueError, KeyError, TypeError) as error:
        typer.echo(json.dumps({'ok':False,'error':str(error)},ensure_ascii=False))
        raise typer.Exit(1)
    typer.echo(json.dumps({'waiting':bool(result and result['status']=='needs_input'),'outcome':result},ensure_ascii=False,indent=2))
