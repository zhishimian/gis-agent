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
    provider: str = "deepseek"
    output_parameter: str = "max_tokens"
    supports_images: bool = True
    image_tokens: int = 1024

    def __post_init__(self) -> None:
        if self.provider not in {"deepseek", "openai", "compatible"}:
            raise ValueError("provider 必须是 deepseek、openai 或 compatible。")
        if not self.model.strip() or not self.base_url.strip() or not self.tokenizer.strip():
            raise ValueError("模型名、服务地址和 tokenizer 必须填写。")
        if not 0 < self.max_tokens < self.context_window:
            raise ValueError("输出预算必须大于零，并小于上下文窗口。")
        if self.output_parameter not in {"max_tokens", "max_completion_tokens"}:
            raise ValueError("不支持的输出预算参数名。")
        if self.image_tokens < 0 or (self.supports_images and self.image_tokens == 0):
            raise ValueError("启用图像输入时，image_tokens 必须大于零。")


@dataclass
class ModelReply:
    message: dict[str, Any]
    model: str
    usage: dict[str, Any] | None
    finish_reason: str | None
    request: dict[str, Any] | None = None

    def metadata(self) -> dict[str, Any]:
        return {"model": self.model, "usage": self.usage, "finish_reason": self.finish_reason,
                **({"request": self.request} if self.request is not None else {})}


class ModelError(RuntimeError):
    pass
