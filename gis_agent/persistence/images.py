import hashlib
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image


IMAGE_FORMATS = {
    "PNG": ("image/png", ".png"),
    "JPEG": ("image/jpeg", ".jpg"),
    "WEBP": ("image/webp", ".webp"),
}
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_SIDE = 8192
MAX_IMAGE_PIXELS = 16_000_000


def save_image(
    path: str, directory: Path, crop: list[int] | None = None,
) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        return {"ok": False, "error": f"图片不存在：{source}"}
    if source.stat().st_size > MAX_IMAGE_BYTES:
        return {"ok": False, "error": "图片超过 8 MiB，请导出较小版本。"}
    data = source.read_bytes()
    if len(data) > MAX_IMAGE_BYTES:
        return {"ok": False, "error": "读取到的图片超过 8 MiB，请重新导出。"}
    source_digest = hashlib.sha256(data).hexdigest()
    with Image.open(BytesIO(data)) as image:
        if image.format not in IMAGE_FORMATS or getattr(image, "is_animated", False):
            return {"ok": False, "error": "请使用静态 PNG、JPEG 或 WebP 图片。"}
        width, height = image.size
        if max(width, height) > MAX_IMAGE_SIDE or width * height > MAX_IMAGE_PIXELS:
            return {"ok": False, "error": "图片超过尺寸限制，请导出较小版本。"}
        source_size = [width, height]
        if crop is not None:
            if not isinstance(crop, list) or len(crop) != 4 or any(type(value) is not int for value in crop):
                return {"ok": False, "error": "crop 必须是四个整数：[left, top, right, bottom]。"}
            left, top, right, bottom = crop
            if not (0 <= left < right <= width and 0 <= top < bottom <= height):
                return {"ok": False, "error": "裁剪框必须位于图片内，并具有正的宽高。"}
        mime_type, suffix = IMAGE_FORMATS[image.format]
        image.load()
        if crop is not None:
            with image.crop(tuple(crop)).convert("RGBA") as region:
                output = BytesIO()
                region.save(output, format="PNG")
                data = output.getvalue()
                width, height = region.size
            mime_type, suffix = IMAGE_FORMATS["PNG"]
    if len(data) > MAX_IMAGE_BYTES:
        return {"ok": False, "error": "裁剪后的 PNG 超过 8 MiB，请缩小区域。"}
    digest = hashlib.sha256(data).hexdigest()
    target = directory.resolve() / f"{digest}{suffix}"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_bytes(data)
    elif target.read_bytes() != data:
        raise ValueError(f"已有图片快照内容发生变化：{target}")
    return {
        "ok": True,
        "source": str(source),
        "image": {
            "version": 1, "path": str(target), "sha256": digest,
            "mime_type": mime_type, "width": width, "height": height, "bytes": len(data),
            "source_sha256": source_digest, "source_size": source_size, "crop": crop,
        },
    }


def load_image(reference: dict[str, Any]) -> bytes:
    if reference["version"] != 1:
        raise ValueError("不支持的图片引用版本。")
    data = Path(reference["path"]).read_bytes()
    if len(data) != reference["bytes"] or hashlib.sha256(data).hexdigest() != reference["sha256"]:
        raise ValueError(f"图片快照校验失败：{reference['path']}")
    return data
