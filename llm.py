import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from openai import APIError, OpenAI
from tokenizers import Tokenizer

from storage import json_text


TokenCounter = Callable[[list[dict[str, Any]], list[dict[str, Any]]], int]


@dataclass(frozen=True)
class ModelConfig:
    model: str = "deepseek-flash"
    base_url: str = "https://api.deepseek.com"
    max_tokens: int = 8192
    context_window: int = 1_048_576
    tokenizer: str = "deepseek-ai/DeepSeek-V4.1-Flash-1017"


def make_token_counter(config: ModelConfig) -> TokenCounter:
    tokenizer = Tokenizer.from_pretrained(config.tokenizer)

    def count(messages: list[dict[str, Any]], schemas: list[dict[str, Any]]) -> int:
        # JSON 计数是估算，另留消息封装余量；实际用量以 API usage 为准。
        text = json_text({"messages": messages, "tools": schemas})
        return len(tokenizer.encode(text, add_special_tokens=False).ids) + 8 * len(messages) + 256

    return count


@dataclass
class ModelReply:
    message: dict[str, Any]
    model: str
    usage: dict[str, Any] | None
    finish_reason: str | None

    def metadata(self) -> dict[str, Any]:
        return {"model": self.model, "usage": self.usage, "finish_reason": self.finish_reason}


def chat(
    client: OpenAI, config: ModelConfig,
    messages: list[dict[str, Any]], schemas: list[dict[str, Any]],
) -> ModelReply:
    arguments: dict[str, Any] = {
        "model": config.model, "messages": messages, "max_tokens": config.max_tokens,
    }
    if schemas:
        arguments["tools"] = schemas
    response = client.chat.completions.create(**arguments)
    choice = response.choices[0]
    return ModelReply(
        message=choice.message.model_dump(include={"role", "content", "tool_calls", "reasoning_content"}),
        model=response.model,
        usage=response.usage.model_dump() if response.usage else None,
        finish_reason=choice.finish_reason,
    )


class AuxiliaryError(ValueError):
    pass


@dataclass
class AuxiliaryCalls:
    chat: Callable[..., ModelReply]
    record: Callable[[dict[str, Any]], None]
    count_tokens: TokenCounter
    token_limit: int = 900_000
    used: int = 0

    def reset(self) -> None:
        self.used = 0

    def ask(self, purpose: str, instructions: str, data: Any) -> Any:
        messages = [
            {"role": "system", "content": instructions + "\n只输出 JSON，不使用 Markdown 代码围栏。"},
            {"role": "user", "content": json_text(data)},
        ]
        if self.count_tokens(messages, []) > self.token_limit:
            raise AuxiliaryError(f"{purpose} 输入超过 token 预算。")
        self.used += 1
        try:
            reply = self.chat(messages, [])
        except APIError as error:
            self.record({'purpose': purpose, 'attempt': self.used, 'error': str(error), 'usage': None})
            raise AuxiliaryError(f'{purpose}: {error}') from error
        self.record({"purpose": purpose, "attempt": self.used, **reply.metadata(), "message": reply.message})
        print("Auxiliary:", purpose, self.used, reply.metadata())
        if reply.finish_reason != "stop" or reply.message.get("tool_calls"):
            raise AuxiliaryError(f"{purpose} 没有返回完整的普通响应。")
        try:
            return json.loads(reply.message.get("content") or "")
        except json.JSONDecodeError as error:
            raise AuxiliaryError(f"{purpose} 返回的 JSON 无效：{error}") from error
