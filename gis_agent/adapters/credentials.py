"""Model credentials shared by workspaces, scoped to a provider and API endpoint."""
from hashlib import sha256
from importlib import import_module
import sys

from gis_agent.config import AppConfig


class Credentials:
    def __init__(self, config: AppConfig):
        endpoint = config.model.base_url.rstrip("/")
        identity = f"{config.model.provider}\n{endpoint}".encode()
        self.service = "OpenGIS-Agent/" + sha256(identity).hexdigest()
        self.backend = None
        self.label = "系统凭据库"
        if sys.platform == "darwin":
            module, name, self.label = "macOS", "Keyring", "macOS 钥匙串"
        elif sys.platform == "win32":
            module, name, self.label = "Windows", "WinVaultKeyring", "Windows 凭据管理器"
        elif sys.platform.startswith("linux"):
            module, name, self.label = "SecretService", "Keyring", "系统密钥环"
        else:
            return
        try:
            backend = getattr(import_module(f"keyring.backends.{module}"), name)
            if backend.priority > 0:
                self.backend = backend()
        except Exception:
            # Desktop credential services can be missing on servers or locked-down systems.
            pass

    def read(self) -> str:
        if self.backend is not None:
            try:
                return self.backend.get_password(self.service, "api-key") or ""
            except Exception:
                self.backend = None
        return ""

    def save(self, key: str) -> bool:
        if self.backend is not None:
            try:
                self.backend.set_password(self.service, "api-key", key)
                return True
            except Exception:
                pass
        return False
