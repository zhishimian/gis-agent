import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from gis_agent.core.context import ContextConfig
from gis_agent.core.memory import MemoryConfig
from gis_agent.core.model import DEEPSEEK_MAX_OUTPUT_TOKENS, ModelConfig


def configured_path(name: str, default: Path, project: Path) -> Path:
    value = Path(os.environ.get(name, str(default))).expanduser()
    return (value if value.is_absolute() else project / value).resolve()


def configured_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name, str(default)).lower()
    if value not in {'true', 'false', '1', '0'}:
        raise ValueError(f'{name} 必须是 true、false、1 或 0。')
    return value in {'true', '1'}


def configured_fonts(project: Path) -> tuple[Path, ...]:
    value = os.environ.get('GIS_AGENT_FONT_FILES')
    if value is None:
        directory = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
        paths = [directory / name for name in ('msyh.ttc', 'arial.ttf')] if os.name == 'nt' else []
    else:
        paths = [Path(item.strip()).expanduser() for item in value.split(';') if item.strip()]
    return tuple((path if path.is_absolute() else project / path).resolve() for path in paths)


def configured_model() -> ModelConfig:
    provider = os.environ.get("GIS_AGENT_PROVIDER", "deepseek")
    if provider not in {"deepseek", "openai", "compatible"}:
        raise ValueError("GIS_AGENT_PROVIDER 必须是 deepseek、openai 或 compatible。")
    deepseek = provider == "deepseek"
    model = os.environ.get("GIS_AGENT_MODEL", "deepseek-flash" if deepseek else "")
    window = os.environ.get("GIS_AGENT_CONTEXT_WINDOW", "1048576" if deepseek else "")
    if not model or not window:
        raise ValueError("请设置 GIS_AGENT_MODEL 和 GIS_AGENT_CONTEXT_WINDOW。")
    flash = deepseek and model == "deepseek-flash"
    base_url = {
        "deepseek": "https://api.deepseek.com",
        "openai": "https://api.openai.com/v1",
        "compatible": "",
    }[provider]
    return ModelConfig(
        model=model,
        base_url=os.environ.get("GIS_AGENT_BASE_URL", base_url),
        max_tokens=int(os.environ.get(
            "GIS_AGENT_MAX_OUTPUT_TOKENS", str(DEEPSEEK_MAX_OUTPUT_TOKENS) if deepseek else "8192",
        )),
        context_window=int(window),
        tokenizer=os.environ.get(
            "GIS_AGENT_TOKENIZER", "deepseek-ai/DeepSeek-V4.1-Flash-1017" if deepseek else "bytes",
        ),
        provider=provider,
        output_parameter=os.environ.get(
            "GIS_AGENT_OUTPUT_PARAMETER", "max_completion_tokens" if provider == "openai" else "max_tokens",
        ),
        supports_images=configured_bool("GIS_AGENT_VISION", flash),
        image_tokens=int(os.environ.get("GIS_AGENT_IMAGE_TOKENS", "1024" if flash else "0")),
    )


@dataclass(frozen=True)
class QGISConfig:
    process_launcher: Path
    python_launcher: Path
    font_files: tuple[Path, ...] = ()

    def __post_init__(self) -> None:
        for path in (self.process_launcher, self.python_launcher):
            if not path.is_file():
                raise FileNotFoundError(f'QGIS 启动器不存在：{path}')


@dataclass(frozen=True)
class AppConfig:
    project: Path
    session_root: Path
    output_root: Path
    qgis: QGISConfig
    model: ModelConfig
    context: ContextConfig
    memory: MemoryConfig | None
    api_key_env: str = 'DEEPSEEK_API_KEY'
    max_retries: int = 3
    trust_env: bool = False

    @classmethod
    def from_env(cls, project: Path) -> 'AppConfig':
        project = project.expanduser().resolve()
        load_dotenv(project / '.env')
        if not os.environ.get('GIS_AGENT_QGIS_DIR'):
            raise ValueError('请在环境变量或 .env 中设置 GIS_AGENT_QGIS_DIR。')
        qgis_dir = configured_path('GIS_AGENT_QGIS_DIR', project, project)
        model = configured_model()
        context = ContextConfig(
            request_token_limit=min(
                int(os.environ.get('GIS_AGENT_REQUEST_TOKENS', '900000')),
                model.context_window - model.max_tokens - 16384,
            ),
        )
        memory = MemoryConfig(
            project=project,
            auto_extract=configured_bool('GIS_AGENT_AUTO_EXTRACT', True),
            qgis_version=os.environ.get('GIS_AGENT_QGIS_VERSION', ''),
        ) if configured_bool('GIS_AGENT_MEMORY', True) else None
        return cls(
            project=project,
            session_root=configured_path('GIS_AGENT_SESSIONS_DIR', project / 'sessions', project),
            output_root=configured_path('GIS_AGENT_OUTPUTS_DIR', project / 'outputs', project),
            qgis=QGISConfig(
                configured_path('GIS_AGENT_QGIS_PROCESS', qgis_dir / 'bin/qgis_process-qgis-ltr.bat', project),
                configured_path('GIS_AGENT_QGIS_PYTHON', qgis_dir / 'bin/python-qgis-ltr.bat', project),
                configured_fonts(project),
            ),
            model=model, context=context, memory=memory,
            api_key_env=os.environ.get('GIS_AGENT_API_KEY_ENV', {
                "deepseek": "DEEPSEEK_API_KEY", "openai": "OPENAI_API_KEY", "compatible": "LLM_API_KEY",
            }[model.provider]),
            max_retries=int(os.environ.get('GIS_AGENT_MAX_RETRIES', '3')),
            trust_env=configured_bool('GIS_AGENT_TRUST_ENV', False),
        )
