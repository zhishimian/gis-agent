from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


TokenCounter = Callable[[list[dict[str, Any]], list[dict[str, Any]]], int]


@dataclass(frozen=True)
class ModelConfig:
    model: str = "deepseek-flash"
    base_url: str = "https://api.deepseek.com"
    max_tokens: int = 8192
    context_window: int = 1_048_576
    tokenizer: str = "deepseek-ai/DeepSeek-V4.1-Flash-1017"


@dataclass
class ModelReply:
    message: dict[str, Any]
    model: str
    usage: dict[str, Any] | None
    finish_reason: str | None

    def metadata(self) -> dict[str, Any]:
        return {"model": self.model, "usage": self.usage, "finish_reason": self.finish_reason}


class ModelError(RuntimeError):
    pass
