from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


def load_local_env(project_root: str | Path) -> None:
    """Load gitignored .env values without overwriting existing environment vars."""
    env_path = Path(project_root) / ".env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


def load_config(path: str | Path) -> tuple[dict[str, Any], Path]:
    """Load YAML configuration and return it with the project root."""
    config_path = Path(path).expanduser().resolve()
    with config_path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)

    project_root = config_path.parent
    load_local_env(project_root)
    for key in ("raw_dir", "reference_dir", "processed_dir", "results_dir"):
        value = Path(config["data"][key])
        if not value.is_absolute():
            config["data"][key] = str((project_root / value).resolve())
    if "music" in config and config["music"].get("cache_file"):
        cache_file = Path(config["music"]["cache_file"])
        if not cache_file.is_absolute():
            config["music"]["cache_file"] = str(
                (project_root / cache_file).resolve()
            )
    return config, project_root


def ensure_output_dirs(config: dict[str, Any]) -> None:
    """Create generated-data and result directories."""
    for key in ("processed_dir", "results_dir"):
        Path(config["data"][key]).mkdir(parents=True, exist_ok=True)
