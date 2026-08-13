"""Create the isolated weather disease AI v2 workspace without processing data."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path


WORKSPACE_NAME = "weather_disease_ai_v2"

EMPTY_DIRECTORIES = (
    "data/interim",
    "data/processed",
    "data/splits",
    "src/data",
    "src/features",
    "src/models",
    "src/explain",
    "src/inference",
    "models",
    "reports/audit",
    "reports/metrics",
    "reports/explanations",
    "reports/logs",
    "tests",
)

REQUIRED_DIRECTORIES = (
    "config",
    "data/raw",
    "data/reference",
    "scripts",
    "legacy_reference",
    *EMPTY_DIRECTORIES,
)

COPY_SPECS = (
    (
        "seasonal_disease_backend/Tool/weather/train_history.xlsx",
        "data/raw/train_history.xlsx",
        "primary patient and disease source data",
        True,
    ),
    (
        "seasonal_disease_backend/Tool/weather/open-meteo-10.79N106.63E6m.csv",
        "data/raw/weather_hcm_history.csv",
        "primary historical weather source data",
        True,
    ),
    (
        "seasonal_disease_backend/Tool/weather/output_weather_ai/weather_ai_positive_cases.csv",
        "data/reference/weather_ai_positive_cases.csv",
        "legacy output for reference only",
        False,
    ),
    (
        "seasonal_disease_backend/Tool/weather/output_weather_ai/weather_daily_features.csv",
        "data/reference/weather_daily_features.csv",
        "legacy output for reference only",
        False,
    ),
    (
        "seasonal_disease_backend/Tool/weather/output_weather_ai/disease_group_catalog_from_ds_mabenh.csv",
        "data/reference/disease_group_catalog_from_ds_mabenh.csv",
        "legacy output for reference only",
        False,
    ),
    (
        "seasonal_disease_backend/Tool/weather/output_weather_ai/dataset_summary.json",
        "data/reference/dataset_summary.json",
        "legacy output for reference only",
        False,
    ),
    (
        "seasonal_disease_backend/scripts/build_weather_ai_dataset.py",
        "legacy_reference/build_weather_ai_dataset.py",
        "legacy implementation for reference only",
        True,
    ),
    (
        "seasonal_disease_backend/Tool/weather/build_weather_ai_dataset_final.py",
        "legacy_reference/build_weather_ai_dataset_final.py",
        "legacy implementation for reference only",
        True,
    ),
    (
        "seasonal_disease_backend/scripts/train_weather_ai_model.py",
        "legacy_reference/train_weather_ai_model.py",
        "legacy implementation for reference only",
        True,
    ),
    (
        "seasonal_disease_backend/app/services/weather_ai_service.py",
        "legacy_reference/weather_ai_service.py",
        "legacy implementation for reference only",
        True,
    ),
    (
        "seasonal_disease_backend/app/routers/weather_ai.py",
        "legacy_reference/weather_ai.py",
        "legacy implementation for reference only",
        True,
    ),
    (
        "seasonal_disease_backend/WEATHER_AI_API_README.md",
        "legacy_reference/WEATHER_AI_API_README.md",
        "legacy documentation for reference only",
        True,
    ),
)

README = """# Weather Disease AI v2

Workspace độc lập để phát triển phiên bản mới của AI dự đoán nhóm bệnh theo thời tiết.

## Cấu trúc

```text
config/             Cấu hình dự án
data/raw/           Dữ liệu nguồn chính, giữ nguyên trạng
data/reference/     Kết quả cũ chỉ dùng để đối chiếu
data/interim/       Dữ liệu trung gian trong các giai đoạn sau
data/processed/     Dữ liệu đã xử lý trong các giai đoạn sau
data/splits/        Các tập train/validation/test trong các giai đoạn sau
src/                Mã nguồn data, features, models, explain và inference
scripts/            Script vận hành workspace
models/             Model sinh ra trong các giai đoạn sau
reports/            Audit, metrics, explanations và logs
tests/              Kiểm thử
legacy_reference/   Bản sao code và tài liệu cũ để tham khảo
```

Hai file dữ liệu nguồn chính là `data/raw/train_history.xlsx` và
`data/raw/weather_hcm_history.csv`. Các file trong `data/reference/` không phải dữ
liệu nguồn chính.

## Chuẩn bị workspace

Chạy từ thư mục `weather_disease_ai_v2`:

```bash
python scripts/prepare_workspace.py
```

Giai đoạn này chỉ chuẩn bị thư mục và sao chép dữ liệu nguyên trạng; chưa xử lý dữ
liệu và chưa huấn luyện mô hình.
"""

CONFIG = """project:
  name: weather_disease_ai_v2
  random_seed: 42

data:
  patient_file: data/raw/train_history.xlsx
  weather_file: data/raw/weather_hcm_history.csv
  patient_sheet: DS-BenhNhan
  disease_sheet: DS-MaBenh

weather:
  windows:
    - 1
    - 3
    - 7
    - 14

model:
  type: CatBoostClassifier
  target: disease_group_id
  weight_column: case_count
"""

GITIGNORE = """data/raw/*
!data/raw/.gitkeep
data/interim/*
!data/interim/.gitkeep
data/processed/*
!data/processed/.gitkeep
data/splits/*
!data/splits/.gitkeep
models/*
!models/.gitkeep
reports/logs/*
!reports/logs/.gitkeep
__pycache__/
.pytest_cache/
.venv/
"""


def find_repository() -> Path:
    """Find the repository from this script's location, independent of cwd."""
    script_path = Path(__file__).resolve()
    for candidate in script_path.parents:
        if (candidate / "seasonal_disease_backend").is_dir() and (
            candidate / WORKSPACE_NAME
        ).is_dir():
            return candidate
    raise RuntimeError("Could not locate the repository root")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_if_safe(path: Path, content: str) -> None:
    encoded = content.encode("utf-8")
    if path.exists():
        if path.read_bytes() != encoded:
            raise FileExistsError(f"Refusing to overwrite different file: {path}")
        return
    path.write_bytes(encoded)


def copy_if_safe(source: Path, destination: Path) -> None:
    if destination.exists():
        if sha256(source) != sha256(destination):
            raise FileExistsError(
                f"Refusing to overwrite destination with different content: {destination}"
            )
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def main() -> None:
    repository = find_repository()
    workspace = repository / WORKSPACE_NAME

    for relative_path in REQUIRED_DIRECTORIES:
        (workspace / relative_path).mkdir(parents=True, exist_ok=True)
    for relative_path in EMPTY_DIRECTORIES:
        (workspace / relative_path / ".gitkeep").touch(exist_ok=True)

    write_if_safe(workspace / "README.md", README)
    write_if_safe(workspace / "requirements.txt", "")
    write_if_safe(workspace / ".gitignore", GITIGNORE)
    write_if_safe(workspace / "config/config.yaml", CONFIG)

    manifest = []
    missing_optional = []
    for source_relative, destination_relative, purpose, required in COPY_SPECS:
        source = repository / source_relative
        destination = workspace / destination_relative
        if not source.is_file():
            if required:
                raise FileNotFoundError(f"Required source file not found: {source}")
            missing_optional.append(source_relative)
            continue

        copy_if_safe(source, destination)
        manifest.append(
            {
                "source_path": source_relative,
                "destination_path": f"{WORKSPACE_NAME}/{destination_relative}",
                "file_size": destination.stat().st_size,
                "sha256": sha256(destination),
                "purpose": purpose,
            }
        )

    manifest_path = workspace / "data/source_manifest.json"
    manifest_content = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    write_if_safe(manifest_path, manifest_content)

    print(f"Workspace ready: {WORKSPACE_NAME}")
    print(f"Manifest entries: {len(manifest)}")
    if missing_optional:
        print("Optional files not found:")
        for path in missing_optional:
            print(f"- {path}")


if __name__ == "__main__":
    main()
