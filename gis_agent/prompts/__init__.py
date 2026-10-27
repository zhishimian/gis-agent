from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined


@lru_cache(maxsize=1)
def environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(Path(__file__).resolve().parent),
        undefined=StrictUndefined, autoescape=False, auto_reload=False,
    )


def render_prompt(name: str, **values: object) -> str:
    return environment().get_template(name).render(**values).strip()
