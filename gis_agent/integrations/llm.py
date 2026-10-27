from typing import Any

from openai import APIError, OpenAI
from tokenizers import Tokenizer

from gis_agent.core.model import ModelConfig, ModelError, ModelReply, TokenCounter
from gis_agent.persistence.json import json_text


def make_token_counter(config: ModelConfig) -> TokenCounter:
    tokenizer = Tokenizer.from_pretrained(config.tokenizer)

    def count(messages: list[dict[str, Any]], schemas: list[dict[str, Any]]) -> int:
        # JSON 计数是估算，另留消息封装余量；实际用量以 API usage 为准。
        text = json_text({"messages": messages, "tools": schemas})
        return len(tokenizer.encode(text, add_special_tokens=False).ids) + 8 * len(messages) + 256

    return count


def chat(
    client: OpenAI, config: ModelConfig,
    messages: list[dict[str, Any]], schemas: list[dict[str, Any]],
) -> ModelReply:
    arguments: dict[str, Any] = {
        "model": config.model, "messages": messages, "max_tokens": config.max_tokens,
    }
    if schemas:
        arguments["tools"] = schemas
    try:
        response = client.chat.completions.create(**arguments)
    except APIError as error:
        raise ModelError(str(error)) from error
    choice = response.choices[0]
    return ModelReply(
        message=choice.message.model_dump(include={"role", "content", "tool_calls", "reasoning_content"}),
        model=response.model,
        usage=response.usage.model_dump() if response.usage else None,
        finish_reason=choice.finish_reason,
    )
