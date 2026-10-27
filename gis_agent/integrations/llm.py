import base64
from typing import Any

from openai import APIError, OpenAI
from tokenizers import Tokenizer

from gis_agent.core.model import ModelConfig, ModelError, ModelReply, TokenCounter
from gis_agent.persistence.images import load_image
from gis_agent.persistence.json import json_text


def request_view(
    messages: list[dict[str, Any]], config: ModelConfig,
) -> tuple[list[dict[str, Any]], int]:
    last_assistant = max(
        (index for index, item in enumerate(messages) if item["role"] == "assistant"), default=-1,
    )
    view = []
    pictures = []
    for index, message in enumerate(messages):
        item = {
            key: message[key]
            for key in ("role", "content", "tool_calls", "tool_call_id", "name", "reasoning_content")
            if key in message
        }
        if config.provider != "deepseek":
            item.pop("reasoning_content", None)
        view.append(item)
        if message["role"] == "tool" and index > last_assistant:
            for reference in message.get("images", []):
                pictures.append({"type": "image_ref", "image": reference})
    if pictures:
        if not config.supports_images:
            raise ModelError("当前模型配置未启用图像输入。")
        view.append({
            "role": "user",
            "content": [
                {"type": "text", "text": "以下图片来自本批 read_image 工具结果，请结合当前任务查看。"},
                *pictures,
            ],
        })
    return view, len(pictures)


def make_token_counter(config: ModelConfig) -> TokenCounter:
    tokenizer = None if config.tokenizer == "bytes" else Tokenizer.from_pretrained(config.tokenizer)

    def count(messages: list[dict[str, Any]], schemas: list[dict[str, Any]]) -> int:
        view, image_count = request_view(messages, config)
        text = json_text({"messages": view, "tools": schemas})
        text_tokens = (
            len(text.encode("utf-8")) if tokenizer is None
            else len(tokenizer.encode(text, add_special_tokens=False).ids)
        )
        return text_tokens + 8 * len(view) + 256 + image_count * config.image_tokens

    return count


def image_part(part: dict[str, Any]) -> dict[str, Any]:
    if part["type"] != "image_ref":
        return part
    reference = part["image"]
    encoded = base64.b64encode(load_image(reference)).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{reference['mime_type']};base64,{encoded}"},
    }


def chat(
    client: OpenAI, config: ModelConfig,
    messages: list[dict[str, Any]], schemas: list[dict[str, Any]],
) -> ModelReply:
    view, _ = request_view(messages, config)
    for message in view:
        if isinstance(message.get("content"), list):
            message["content"] = [image_part(part) for part in message["content"]]
    arguments: dict[str, Any] = {
        "model": config.model, "messages": view, config.output_parameter: config.max_tokens,
    }
    if schemas:
        arguments["tools"] = schemas
    if len(json_text(arguments).encode("utf-8")) > 32 * 1024 * 1024:
        raise ModelError("请求正文超过本地 32 MiB 限制，请减少同批图片或导出较小版本。")
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
