from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional during pure unit tests
    load_dotenv = None


CONFIG_FILE = "vault.json"
DATA_DIR = ".vamos-vault"
FREE_FILE_LIMIT_BYTES = 2 * 1024 * 1024 * 1024
PREMIUM_FILE_LIMIT_BYTES = 4 * 1024 * 1024 * 1024


DEFAULT_CONFIG: dict[str, Any] = {
    "telegram": {
        "target": "me",
        "session_name": "vamos.session",
    },
    "vault": {
        "database": f"{DATA_DIR}/vault.db",
        "caption_limit": 1024,
        "max_file_bytes": FREE_FILE_LIMIT_BYTES,
        "send_as_document": True,
    },
}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(base_dir: Path | None = None) -> dict[str, Any]:
    base_dir = base_dir or Path.cwd()
    if load_dotenv is not None:
        load_dotenv(base_dir / ".env")

    config = copy.deepcopy(DEFAULT_CONFIG)
    config_path = base_dir / CONFIG_FILE
    if config_path.exists():
        config = deep_merge(config, json.loads(config_path.read_text(encoding="utf-8")))

    env_target = os.getenv("TELEGRAM_TARGET")
    if env_target:
        config["telegram"]["target"] = env_target

    env_db = os.getenv("VAMOS_VAULT_DB")
    if env_db:
        config["vault"]["database"] = env_db

    env_max = os.getenv("VAMOS_MAX_FILE_BYTES")
    if env_max:
        config["vault"]["max_file_bytes"] = int(env_max)

    return config


def write_config(
    base_dir: Path,
    *,
    target: str,
    premium: bool = False,
    database: str | None = None,
) -> Path:
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["telegram"]["target"] = target
    if premium:
        config["vault"]["max_file_bytes"] = PREMIUM_FILE_LIMIT_BYTES
    if database:
        config["vault"]["database"] = database

    path = base_dir / CONFIG_FILE
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    (base_dir / DATA_DIR).mkdir(exist_ok=True)
    return path


def resolve_data_path(base_dir: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return base_dir / path


def telegram_credentials() -> tuple[int | None, str | None]:
    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")
    return (int(api_id) if api_id else None, api_hash)

