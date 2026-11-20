"""Scrollback-friendly interactive terminal frontend for OpenGIS."""
import os
from contextlib import ExitStack
from pathlib import Path
import signal
from uuid import uuid4
from urllib.parse import urlsplit

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.markdown import Markdown
from rich.text import Text

from gis_agent.adapters.credentials import Credentials
from gis_agent.adapters.welcome import ACCENT, DIVIDER, LAND, welcome
from gis_agent.application import Conversation, open_conversation
from gis_agent.config import AppConfig
from gis_agent.core.events import AgentEvent
from gis_agent.core.model import ModelError
from gis_agent.persistence.sessions import SessionStore, folder_sessions

COMMANDS = {
    "/help": "查看命令和快捷键",
    "/status": "查看模型、会话和成果目录",
    "/new": "在此文件夹新建会话，可指定名称",
    "/resume": "列出此文件夹的会话，或加上名称继续",
    "/key": "设置或更新模型密钥",
    "/cancel": "取消正在等待补充的任务",
    "/exit": "退出终端，保留会话",
}
LABELS = {
    "answer": "回答", "completed": "已完成", "partial": "部分完成",
    "needs_input": "需要补充", "blocked": "受阻", "cancelled": "已取消",
}


class CommandCompleter(Completer):
    def __init__(self, root: Path):
        self.root = root

    def get_completions(self, document, complete_event):
        prefix = document.text_before_cursor
        if prefix.startswith("/resume "):
            partial = prefix[len("/resume "):]
            for name in folder_sessions(self.root):
                if name.startswith(partial):
                    yield Completion(name, start_position=-len(partial))
        elif prefix.startswith("/") and " " not in prefix:
            for name, description in COMMANDS.items():
                if name.startswith(prefix):
                    yield Completion(name, start_position=-len(prefix), display_meta=description)


def make_prompt(console: Console, root: Path) -> PromptSession:
    keys = KeyBindings()

    @keys.add("enter")
    def submit(event):
        event.current_buffer.validate_and_handle()

    @keys.add("escape", "enter")
    def newline(event):
        event.current_buffer.insert_text("\n")

    return PromptSession(
        multiline=True,
        key_bindings=keys,
        completer=CommandCompleter(root),
        reserve_space_for_menu=0,
        prompt_continuation="  ",
        style=Style.from_dict({
            "accent": "bold" if console.no_color else f"bold {ACCENT}",
            "muted": "ansibrightblack",
        }),
    )


class Activity:
    def __init__(self, console: Console):
        self.console = console
        self.spinner = console.status("正在思考…", spinner="dots", spinner_style=ACCENT)

    def event(self, event: AgentEvent) -> None:
        tool = event.payload.get("tool", "")
        if event.type == "tool_started":
            self.spinner.update(Text.assemble("正在执行 ", (tool, "bold")))
        elif event.type == "tool_finished":
            ok = event.payload.get("ok") is not False
            if tool != "finish_task" or not ok:
                elapsed = event.payload.get("elapsed_ms", 0) / 1000
                self.console.print(Text.assemble(
                    ("  ✓ " if ok else "  × ", LAND if ok else ACCENT),
                    tool, (f"  {elapsed:.1f}s", "dim"),
                ))
            self.spinner.update("正在思考…")

    def run(self, conversation: Conversation, action) -> dict:
        previous = signal.getsignal(signal.SIGINT)

        def stop(signum, frame):
            conversation.request_stop()

        with self.spinner:
            self.spinner.update("正在思考…  ·  Ctrl+C 停止")
            signal.signal(signal.SIGINT, stop)
            try:
                return action()
            finally:
                signal.signal(signal.SIGINT, previous)


def result_view(console: Console, result: dict) -> None:
    status = result.get("status", "")
    console.print(Text.assemble(("● OpenGIS", f"bold {ACCENT}"), ("  " + LABELS.get(status, status), "dim")))
    console.print(Markdown(result["summary"], code_theme="ansi_dark"))
    if result.get("question") and result["question"] != result["summary"]:
        console.print(Text(result["question"], style="bold"))
    for item in result.get("unresolved", []):
        console.print(Text.assemble(("  待处理  ", "dim"), item))
    for path in result.get("artifacts", []):
        console.print(Text.assemble(("  ↳ ", LAND), path))
    console.print()


def prompt_key(console: Console, config: AppConfig, credentials: Credentials) -> str:
    host = urlsplit(config.model.base_url).hostname or config.model.provider
    console.print(Text.assemble(("连接模型  ", f"bold {ACCENT}"), config.model.model, ("  " + host, "dim")))
    account_url = {
        "api.deepseek.com": "https://platform.deepseek.com/api_keys",
        "api.openai.com": "https://platform.openai.com/api-keys",
    }.get(host)
    if account_url:
        console.print(Text.assemble(("获取密钥  ", "dim"), (account_url, f"link {account_url}")))
    destination = f"保存到{credentials.label}" if credentials.backend is not None else "仅用于本次启动"
    console.print(Text(f"输入 API Key，{destination}。直接回车可跳过。", style="dim"))
    try:
        key = PromptSession(erase_when_done=True).prompt("API Key（隐藏输入） › ", is_password=True).strip()
    except (EOFError, KeyboardInterrupt):
        return ""
    if key:
        saved = credentials.save(key)
        message = f"密钥已保存到{credentials.label}。" if saved else "密钥仅用于本次启动。"
        console.print(Text(message, style=ACCENT))
        if os.environ.get(config.api_key_env, "").strip():
            console.print(Text(f"下次启动将优先使用 {config.api_key_env} 中配置的密钥。", style="dim"))
    return key


def run_terminal(config: AppConfig, session: str | None) -> None:
    console = Console(highlight=False)
    prompt = make_prompt(console, config.session_root)
    credentials = Credentials(config)
    key = os.environ.get(config.api_key_env, "").strip() or credentials.read()
    session = session or uuid4().hex[:12]
    SessionStore(config.session_root, session)
    activity = Activity(console)
    welcome(console, config, session, tuple(folder_sessions(config.session_root)))
    if not key:
        key = prompt_key(console, config, credentials)
    while True:
        store = SessionStore(config.session_root, session)
        conversation: Conversation | None = None
        with ExitStack() as resources:
            def ensure_conversation() -> Conversation:
                nonlocal conversation
                if conversation is None:
                    conversation = resources.enter_context(open_conversation(
                        config, session, api_key=key, on_event=activity.event,
                    ))
                return conversation

            if key and store.path.is_file():
                active = ensure_conversation()
                if active.pending:
                    result_view(console, activity.run(active, active.resume))
                elif active.pending_answer:
                    result_view(console, activity.run(active, active.continue_answer))
                elif active.waiting:
                    result_view(console, active.waiting)
                elif active.messages:
                    last = active.messages[-1]
                    if last["role"] == "assistant" and last.get("content"):
                        console.print("上次回复", style="dim")
                        console.print(Markdown(last["content"]))
            while True:
                waiting = bool(conversation and conversation.waiting)
                try:
                    text = prompt.prompt(
                        [("class:accent", " 补充 › " if waiting else " ❯ ")],
                        placeholder=[("class:muted", "补充任务信息…" if waiting else "描述 GIS 任务，或输入 / 查看命令")],
                    ).strip()
                except KeyboardInterrupt:
                    continue
                except EOFError:
                    text = "/exit"
                if not text:
                    continue
                command, *arguments = text.split(maxsplit=1)
                if command in COMMANDS and command not in {"/resume", "/new"} and arguments:
                    console.print(Text(f"请单独输入 {command}。", style="dim"))
                    continue
                if text in {"/exit", "exit"}:
                    if store.path.exists():
                        console.print(Text.assemble(("继续此会话  ", "dim"), f"opengis --session {session}"))
                    return
                if text == "/help":
                    for cmd, desc in COMMANDS.items():
                        console.print(Text.assemble((f"  {cmd:<10}", ACCENT), desc))
                    console.print("  Enter 发送 · Esc 后按 Enter 换行 · Ctrl+C 停止任务 · Ctrl+D 退出", style="dim")
                elif text == "/status":
                    for name, value in (
                        ("工作文件夹", config.project), ("会话", session), ("模型", config.model.model),
                        ("密钥", "已配置" if key else f"待配置 · {config.api_key_env}"),
                        ("成果", config.output_root / session),
                    ):
                        console.print(Text.assemble((f"  {name}  ", "dim"), str(value)))
                elif text == "/key":
                    new_key = prompt_key(console, config, credentials)
                    if new_key:
                        key = new_key
                        break
                elif command == "/new":
                    name = arguments[0] if arguments else uuid4().hex[:12]
                    try:
                        target = SessionStore(config.session_root, name)
                        target.create()
                    except FileExistsError:
                        console.print(Text("同名会话已存在。输入 /resume " + name + " 继续。", style=ACCENT))
                        continue
                    except (ValueError, OSError) as error:
                        console.print(Text(str(error), style=ACCENT))
                        continue
                    session = name
                    console.print(Text.assemble((config.project.name + " / ", "dim"), (name, ACCENT)))
                    break
                elif command == "/resume":
                    if not arguments:
                        recent = folder_sessions(config.session_root)
                        console.print(Text(str(config.project), style="bold"))
                        for name in recent:
                            console.print(Text.assemble(("  · ", DIVIDER), name, ("  当前" if name == session else "", ACCENT)))
                        console.print("输入 /resume 名称继续" if recent else "暂无已保存会话，可用 /new 名称新建。", style="dim")
                    else:
                        try:
                            target = SessionStore(config.session_root, arguments[0])
                            if not target.path.is_file():
                                raise ValueError("找不到这个已保存的会话。")
                        except ValueError as error:
                            console.print(Text(str(error), style=ACCENT))
                            continue
                        session = target.session_id
                        console.print(Text.assemble((config.project.name + " / ", "dim"), (session, ACCENT)))
                        break
                elif text in {"/cancel", "cancel"}:
                    if waiting:
                        assert conversation is not None
                        result_view(console, conversation.cancel())
                    else:
                        console.print("当前没有等待补充的任务。", style="dim")
                elif not key:
                    console.print(Text.assemble(("  /key", ACCENT), " 连接模型后即可发送任务。"))
                else:
                    try:
                        active = ensure_conversation()
                        result_view(console, activity.run(active, lambda: active.send(text)))
                    except (ValueError, ModelError, OSError) as error:
                        console.print(Text(str(error), style=ACCENT))
