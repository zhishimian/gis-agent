import logging
from pathlib import Path
from typing import Annotated
from uuid import uuid4

import typer

from gis_agent.application import open_conversation
from gis_agent.config import AppConfig


app = typer.Typer(add_completion=False)


@app.command()
def chat(
    project: Annotated[Path, typer.Option(help='项目目录，也是默认记录目录。')] = Path(__file__).resolve().parents[1],
    session: Annotated[str | None, typer.Option(help='会话 ID；不填时交互输入。')] = None,
) -> None:
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
