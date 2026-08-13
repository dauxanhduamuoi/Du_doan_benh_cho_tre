"""Run GPU smoke test, four experiments, and validation-only selection."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.models.training import run_training_stage


def main() -> None:
    pipeline = run_training_stage(PROJECT_ROOT)
    selected = pipeline.selected_result
    assert selected is not None
    metrics = selected["validation_metrics"]["case_weighted"]
    print("GPU training and validation-only selection completed.")
    print(f"Selected experiment: {selected['experiment']}")
    print(f"Validation weighted Top-5: {metrics['top_5_accuracy']:.4%}")
    print("Checkpoint: reports/logs/selected_model_gpu_checkpoint.cbm")
    print("Next: python scripts/05_evaluate_model.py")
    print("Test rows scored during selection: 0")


if __name__ == "__main__":
    main()
