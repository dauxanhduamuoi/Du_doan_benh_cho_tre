"""Evaluate test once, save final artifacts, and verify the GPU model."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.models.training import run_evaluation_stage


def main() -> None:
    pipeline = run_evaluation_stage(PROJECT_ROOT)
    assert pipeline.test_payload is not None
    metrics = pipeline.test_payload["metrics"]["case_weighted"]
    print("One-time held-out test evaluation completed.")
    print(f"Test weighted Top-5: {metrics['top_5_accuracy']:.4%}")
    print(f"Test weighted log loss: {metrics['multiclass_log_loss']:.6f}")
    print("Report: reports/MODEL_TRAINING_REPORT.md")


if __name__ == "__main__":
    main()
