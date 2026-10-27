import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from gis_agent.core.context import ContextConfig
from gis_agent.core.memory import MemoryConfig
from gis_agent.core.model import ModelConfig


def configured_path(name: str, default: Path, project: Path) -> Path:
    value = Path(os.environ.get(name, str(default))).expanduser()
    return (value if value.is_absolute() else project / value).resolve()


def configured_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name, str(default)).lower()
    if value not in {'true', 'false', '1', '0'}:
        raise ValueError(f'{name} 必须是 true、false、1 或 0。')
    return value in {'true', '1'}


@dataclass(frozen=True)
class QGISConfig:
    process_launcher: Path
    python_launcher: Path

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
        model = ModelConfig(
            model=os.environ.get('GIS_AGENT_MODEL', 'deepseek-flash'),
            base_url=os.environ.get('GIS_AGENT_BASE_URL', 'https://api.deepseek.com'),
            max_tokens=int(os.environ.get('GIS_AGENT_MAX_OUTPUT_TOKENS', '8192')),
            context_window=int(os.environ.get('GIS_AGENT_CONTEXT_WINDOW', '1048576')),
            tokenizer=os.environ.get('GIS_AGENT_TOKENIZER', 'deepseek-ai/DeepSeek-V4.1-Flash-1017'),
        )
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
            ),
            model=model, context=context, memory=memory,
            api_key_env=os.environ.get('GIS_AGENT_API_KEY_ENV', 'DEEPSEEK_API_KEY'),
            max_retries=int(os.environ.get('GIS_AGENT_MAX_RETRIES', '3')),
            trust_env=configured_bool('GIS_AGENT_TRUST_ENV', False),
        )
