from functools import partial
from pathlib import Path

from gis_agent.persistence.images import save_image
from gis_agent.tools.base import Tool


def make_image_tool(directory: Path) -> Tool:
    return Tool(
        name="read_image",
        description=(
            "读取本地静态 PNG、JPEG 或 WebP，下一次模型请求会实际包含图片。"
            "省略 crop 时查看整图；crop 为原图像素坐标 [left, top, right, bottom]，右下边界不包含。"
            "用于查看地图、图例和标注；需要再次查看时重新调用。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "crop": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 0},
                    "minItems": 4,
                    "maxItems": 4,
                    "description": "原图像素区域 [left, top, right, bottom]，省略时读取整图。",
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        function=partial(save_image, directory=directory),
    )
