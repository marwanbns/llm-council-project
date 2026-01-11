"""
Pour ce script il utilise soit la config dans config.yaml, si le fichier n'existe pas ou n'est pas complet il utilise la config definit dans les
variables d'environnement comme sur le repo github original du llm council et si pas de variables d'environnement il utilise le build par defaut.
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from loguru import logger
try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None


@dataclass
class LLMNode:
    name: str
    host: str
    port: int
    model: str
    is_chairman: bool = False

    @property
    def base_url(self) -> str:
        return f"{self.host}:{self.port}"

    @property
    def chat_url(self) -> str:
        return f"{self.base_url}/api/chat"

    @property
    def api_url(self) -> str:
        return f"{self.base_url}/api/generate"

    @property
    def health_url(self) -> str:
        return f"{self.base_url}/api/tags"


@dataclass
class CouncilConfig:
    council_members: List[LLMNode] = field(default_factory=list)
    chairman: Optional[LLMNode] = None

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    debug: bool = True

    llm_timeout: int = 300
    health_check_interval: int = 30

    chairman_mode: str = "local"  # local | remote
    chairman_remote_base_url: Optional[str] = None
    chairman_remote_endpoint: str = "/api/chairman/synthesize"
    chairman_remote_timeout_s: int = 900


# Helper dans le cas du .env
def _env_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning(f"Invalid int {key}={raw!r}, using {default}")
        return default


def _env_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


# Dans le casdu fichier de config yaml
def _yaml_load() -> Dict[str, Any]:
    path = os.getenv("CONFIG_YAML_PATH", "config.yaml")
    p = Path(path)

    if not p.exists():
        return {}

    if yaml is None:
        logger.warning("config.yaml found but PyYAML not installed. Run: pip install pyyaml")
        return {}

    try:
        with p.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            logger.warning("config.yaml root must be a mapping/dict; ignoring.")
            return {}
        return data
    except Exception as e:
        logger.warning(f"Failed to load {p}: {e}")
        return {}


def _node_from_dict(d: Dict[str, Any], *, is_chairman: bool) -> LLMNode:
    return LLMNode(
        name=str(d.get("name", "Chairman" if is_chairman else "Counselor")),
        host=str(d.get("host", "http://localhost")),
        port=int(d.get("port", 11434)),
        model=str(d.get("model", "mistral" if is_chairman else "llama3.2")),
        is_chairman=is_chairman,
    )


# Dans le cas du .env
def _load_council_from_env() -> List[LLMNode]:
    members: List[LLMNode] = []
    i = 1
    while True:
        name = os.getenv(f"COUNCIL_LLM_{i}_NAME")
        if not name:
            break
        host = os.getenv(f"COUNCIL_LLM_{i}_HOST", "http://localhost")
        port = _env_int(f"COUNCIL_LLM_{i}_PORT", 11434)
        model = os.getenv(f"COUNCIL_LLM_{i}_MODEL", "llama3.2")
        members.append(LLMNode(name=name, host=host, port=port, model=model, is_chairman=False))
        i += 1
    return members


def _load_chairman_from_env() -> LLMNode:
    return LLMNode(
        name=os.getenv("CHAIRMAN_NAME", "Chairman"),
        host=os.getenv("CHAIRMAN_HOST", "http://localhost"),
        port=_env_int("CHAIRMAN_PORT", 11434),
        model=os.getenv("CHAIRMAN_MODEL", "mistral"),
        is_chairman=True,
    )


# Configuration de defaut
def _demo_defaults() -> tuple[List[LLMNode], LLMNode]:
    return (
        [
            LLMNode(name="Counselor-Alpha", host="http://localhost", port=11434, model="llama3.2"),
            LLMNode(name="Counselor-Beta", host="http://localhost", port=11434, model="mistral"),
            LLMNode(name="Counselor-Gamma", host="http://localhost", port=11434, model="phi3"),
        ],
        LLMNode(name="Chairman", host="http://localhost", port=11434, model="mistral", is_chairman=True),
    )


# Loader principal
def load_config() -> CouncilConfig:
    cfg = CouncilConfig()

    y = _yaml_load()

    # Yaml
    app = y.get("app") if isinstance(y.get("app"), dict) else {}
    if isinstance(app, dict):
        cfg.api_host = str(app.get("api_host", cfg.api_host))
        cfg.api_port = int(app.get("api_port", cfg.api_port))
        cfg.debug = bool(app.get("debug", cfg.debug))
        cfg.llm_timeout = int(app.get("llm_timeout", cfg.llm_timeout))
        cfg.health_check_interval = int(app.get("health_check_interval", cfg.health_check_interval))
    else:
        # env
        cfg.api_host = os.getenv("API_HOST", cfg.api_host)
        cfg.api_port = _env_int("API_PORT", cfg.api_port)
        cfg.debug = _env_bool("DEBUG", cfg.debug)
        cfg.llm_timeout = _env_int("LLM_TIMEOUT", cfg.llm_timeout)
        cfg.health_check_interval = _env_int("HEALTH_CHECK_INTERVAL", cfg.health_check_interval)

    # Differents llm
    council = y.get("council") if isinstance(y.get("council"), dict) else {}
    members_yaml = council.get("members") if isinstance(council, dict) else None

    if isinstance(members_yaml, list) and members_yaml:
        cfg.council_members = [_node_from_dict(m, is_chairman=False) for m in members_yaml if isinstance(m, dict)]
    else:
        cfg.council_members = _load_council_from_env()

    # Pour le chairman
    chairman = y.get("chairman") if isinstance(y.get("chairman"), dict) else {}
    if isinstance(chairman, dict):
        mode = str(chairman.get("mode", "local")).strip().lower()
        cfg.chairman_mode = mode if mode in {"local", "remote"} else "local"

        remote = chairman.get("remote") if isinstance(chairman.get("remote"), dict) else {}
        if isinstance(remote, dict):
            cfg.chairman_remote_base_url = remote.get("base_url") or None
            cfg.chairman_remote_endpoint = str(remote.get("endpoint", cfg.chairman_remote_endpoint))
            cfg.chairman_remote_timeout_s = int(remote.get("timeout_s", cfg.chairman_remote_timeout_s))

        local = chairman.get("local") if isinstance(chairman.get("local"), dict) else {}
        if isinstance(local, dict) and local:
            cfg.chairman = _node_from_dict(local, is_chairman=True)
        else:
            cfg.chairman = _load_chairman_from_env()
    else:
        cfg.chairman_mode = "local"
        cfg.chairman = _load_chairman_from_env()

    # Configuration de defaut si ni le yaml ni l'env n'ont été utilisé
    if not cfg.council_members or cfg.chairman is None:
        logger.warning("Config incomplete; applying demo defaults.")
        demo_members, demo_chair = _demo_defaults()
        cfg.council_members = cfg.council_members or demo_members
        cfg.chairman = cfg.chairman or demo_chair

    logger.info(f"Config: council_members={len(cfg.council_members)}")
    logger.info(f"Config: chairman_mode={cfg.chairman_mode}")
    if cfg.chairman_mode == "remote":
        logger.info(f"Config: chairman_remote={cfg.chairman_remote_base_url}{cfg.chairman_remote_endpoint}")
    else:
        logger.info(f"Config: chairman_local={cfg.chairman.name} ({cfg.chairman.model})")

    return cfg


_CONFIG: Optional[CouncilConfig] = None


def get_config() -> CouncilConfig:
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = load_config()
    return _CONFIG