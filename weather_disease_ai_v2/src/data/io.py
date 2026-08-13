"""Workspace paths, configuration, hashing, and deterministic writers."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


SOURCE_FALLBACKS = {
    "train_history.xlsx": "seasonal_disease_backend/Tool/weather/train_history.xlsx",
    "weather_hcm_history.csv": (
        "seasonal_disease_backend/Tool/weather/open-meteo-10.79N106.63E6m.csv"
    ),
}


def find_project_root(start: Path | None = None) -> Path:
    """Locate ``weather_disease_ai_v2`` without depending on the current directory."""
    origin = (start or Path(__file__)).resolve()
    candidates = [origin, *origin.parents] if origin.is_dir() else list(origin.parents)
    for candidate in candidates:
        if (
            candidate.name == "weather_disease_ai_v2"
            and (candidate / "config/config.yaml").is_file()
        ):
            return candidate
    raise RuntimeError("Could not locate the weather_disease_ai_v2 workspace")


def load_config(project_root: Path) -> dict[str, Any]:
    config_path = project_root / "config/config.yaml"
    with config_path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    if not isinstance(config, dict):
        raise ValueError(f"Invalid YAML configuration: {config_path}")
    return config


def ensure_source_files(project_root: Path, config: dict[str, Any]) -> tuple[Path, Path]:
    """Ensure the two raw files exist, copying legacy sources without modifying them."""
    patient_path = project_root / config["data"]["patient_file"]
    weather_path = project_root / config["data"]["weather_file"]
    repository_root = project_root.parent

    for destination in (patient_path, weather_path):
        if destination.is_file():
            continue
        fallback_relative = SOURCE_FALLBACKS.get(destination.name)
        fallback = repository_root / fallback_relative if fallback_relative else None
        if fallback is not None and fallback.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(fallback, destination)
        if not destination.is_file():
            raise FileNotFoundError(
                f"Required source file is missing and no fallback was found: {destination}"
            )
    return patient_path, weather_path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative_posix(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8", lineterminator="\n")


def write_csv_gzip(path: Path, frame: pd.DataFrame) -> None:
    """Write byte-reproducible gzip CSV output."""
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(
        path,
        index=False,
        encoding="utf-8",
        lineterminator="\n",
        compression={"method": "gzip", "compresslevel": 6, "mtime": 0},
    )
