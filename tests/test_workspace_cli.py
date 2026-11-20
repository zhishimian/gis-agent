from io import StringIO
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from gis_agent import cli
from gis_agent.adapters import credentials
from gis_agent.config import AppConfig
from gis_agent.persistence.sessions import SessionStore, folder_sessions


def test_working_folder_owns_sessions(tmp_path, monkeypatch):
    homes = [tmp_path / "城区 A", tmp_path / "城区 B"]
    seen = []
    monkeypatch.setattr(cli, "chat", lambda project, session: seen.append(project))
    for folder in homes:
        folder.mkdir()
        monkeypatch.chdir(folder)
        assert CliRunner().invoke(cli.app, []).exit_code == 0
        config = AppConfig.from_env(folder)
        store = SessionStore(config.session_root, "学校分布")
        store.create()
        store.save([{"role": "user", "content": folder.name}])
        with pytest.raises(FileExistsError):
            store.create()
        assert store.read_record()[0]["content"] == folder.name
        assert config.output_root == folder / "outputs"
    assert seen == homes
    SessionStore(homes[0] / "sessions", "仅在城区A").create()
    assert folder_sessions(homes[1] / "sessions") == ["学校分布"]
    assert CliRunner().invoke(cli.app, ["--folder", str(homes[0])]).exit_code == 0
    assert seen[-1] == homes[0]


@pytest.mark.parametrize(("platform", "module", "name"), [
    ("darwin", "macOS", "Keyring"), ("win32", "Windows", "WinVaultKeyring"),
    ("linux", "SecretService", "Keyring"),
])
def test_endpoint_scoped_system_credentials(monkeypatch, platform, module, name):
    items = {}

    class Store:
        priority = 1

        def get_password(self, service, account):
            return items.get((service, account))

        def set_password(self, service, account, key):
            items[service, account] = key

    def load(path):
        assert path == "keyring.backends." + module
        return SimpleNamespace(**{name: Store})

    monkeypatch.setattr(credentials, "sys", SimpleNamespace(platform=platform))
    monkeypatch.setattr(credentials, "import_module", load)
    config = SimpleNamespace(model=SimpleNamespace(provider="compatible", base_url="https://one.invalid/v1"))
    first = credentials.Credentials(config)
    assert first.save("example-test-value")
    assert credentials.Credentials(config).read() == "example-test-value"
    config.model.base_url = "https://two.invalid/v1"
    assert credentials.Credentials(config).read() == ""

    def denied(*args):
        raise PermissionError

    monkeypatch.setattr(Store, "set_password", denied)
    assert first.save("another-test-value") is False
    monkeypatch.setattr(Store, "get_password", denied)
    assert first.read() == ""


def test_first_run_password_prompt_and_skip(tmp_path, monkeypatch):
    from prompt_toolkit import PromptSession
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput
    from rich.console import Console
    from gis_agent.adapters import terminal

    cfg = AppConfig.from_env(tmp_path)
    saved = []
    vault = SimpleNamespace(backend=True, label="测试凭据库", save=lambda value: saved.append(value) or True)
    out = StringIO()
    console = Console(file=out, width=80)
    with create_pipe_input() as keyboard:
        monkeypatch.setattr(terminal, "PromptSession", lambda **opts: PromptSession(
            input=keyboard, output=DummyOutput(), **opts,
        ))
        keyboard.send_text("private-test-value\r")
        assert terminal.prompt_key(console, cfg, vault) == "private-test-value"
        keyboard.send_text("\r")
        assert terminal.prompt_key(console, cfg, vault) == ""
    assert saved == ["private-test-value"]
    assert saved[0] not in out.getvalue()
    assert "测试凭据库" in out.getvalue()
