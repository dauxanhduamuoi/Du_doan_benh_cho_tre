"""Single GPU training pipeline shared by the CLI and Jupyter Notebook."""

from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

import catboost
import numpy as np
import pandas as pd
from catboost import CatBoostClassifier, Pool

from src.data.io import load_config, relative_posix, sha256_file, write_csv, write_json
from src.models.baseline import fit_frequency_baseline
from src.models.common import (
    CATEGORICAL_FEATURES,
    EXCLUDED_FEATURE_COLUMNS,
    EXPERIMENT_LABELS,
    EXPERIMENT_WINDOWS,
    TARGET_COLUMN,
    WEIGHT_COLUMN,
    TrainingData,
    environment_diagnostics,
    experiment_feature_sets,
    prepare_features,
    validate_and_load_inputs,
)
from src.models.evaluation import (
    evaluate_model_on_split,
    experiment_comparison_frame,
    select_best_experiment,
    write_training_report,
)
from src.models.metrics import compute_metrics


@dataclass(frozen=True)
class GPUTrainingConfig:
    device: str = "GPU"
    gpu_id: str = "0"
    iterations: int = 1000
    depth: int = 8
    learning_rate: float = 0.05
    random_seed: int = 42
    early_stopping_rounds: int = 80
    verbose: int = 50
    loss_function: str = "MultiClass"
    eval_metric: str = "MultiClass"
    allow_writing_files: bool = False

    def __post_init__(self) -> None:
        if self.device != "GPU":
            raise ValueError("This pipeline is GPU-only; device must be 'GPU'")
        if not str(self.gpu_id).strip():
            raise ValueError("gpu_id must identify at least one GPU")

    @classmethod
    def from_project(cls, project_root: Path) -> "GPUTrainingConfig":
        values = load_config(project_root)["model"]
        return cls(
            device=str(values.get("device", "GPU")),
            gpu_id=str(values.get("gpu_id", "0")),
            iterations=int(values.get("iterations", 1000)),
            depth=int(values.get("depth", 8)),
            learning_rate=float(values.get("learning_rate", 0.05)),
            random_seed=int(load_config(project_root)["project"].get("random_seed", 42)),
            early_stopping_rounds=int(values.get("early_stopping_rounds", 80)),
            verbose=int(values.get("verbose", 50)),
            loss_function=str(values.get("loss_function", "MultiClass")),
            eval_metric=str(values.get("eval_metric", "MultiClass")),
            allow_writing_files=bool(values.get("allow_writing_files", False)),
        )

    def catboost_parameters(self) -> dict[str, Any]:
        return {
            "task_type": "GPU",
            "devices": self.gpu_id,
            "loss_function": self.loss_function,
            "eval_metric": self.eval_metric,
            "iterations": self.iterations,
            "depth": self.depth,
            "learning_rate": self.learning_rate,
            "random_seed": self.random_seed,
            "early_stopping_rounds": self.early_stopping_rounds,
            "verbose": self.verbose,
            "allow_writing_files": self.allow_writing_files,
        }


def format_elapsed(seconds: float) -> str:
    total = int(round(seconds))
    minutes, remaining = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {remaining:02d}s"
    return f"{minutes}m {remaining:02d}s"


class _TeeStream:
    def __init__(self, *streams: TextIO) -> None:
        self.streams = streams

    def write(self, text: str) -> int:
        for stream in self.streams:
            stream.write(text)
            stream.flush()
        return len(text)

    def flush(self) -> None:
        for stream in self.streams:
            stream.flush()


class TrainingPipeline:
    """Stateful, stepwise GPU pipeline used identically by Notebook and CLI."""

    CHECKPOINT_MODEL = "reports/logs/selected_model_gpu_checkpoint.cbm"
    CHECKPOINT_STATE = "reports/logs/training_gpu_checkpoint.json"

    def __init__(self, project_root: Path, config: GPUTrainingConfig | None = None) -> None:
        self.project_root = project_root.resolve()
        self.config = config or GPUTrainingConfig.from_project(self.project_root)
        self.log_path = self.project_root / "reports/logs/training_gpu.log"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.data: TrainingData | None = None
        self.feature_sets: dict[str, list[str]] = {}
        self.baseline_payload: dict[str, Any] | None = None
        self.smoke_result: dict[str, Any] | None = None
        self.experiment_results: list[dict[str, Any]] = []
        self.models: dict[str, CatBoostClassifier] = {}
        self.selected_result: dict[str, Any] | None = None
        self.selected_model: CatBoostClassifier | None = None
        self.selection_payload: dict[str, Any] | None = None
        self.validation_evaluation: dict[str, Any] | None = None
        self.test_payload: dict[str, Any] | None = None
        self.test_evaluation: dict[str, Any] | None = None
        self.final_verification: dict[str, Any] | None = None

    def _log(self, message: str) -> None:
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        line = f"[{timestamp}] {message}"
        print(line, flush=True)
        with self.log_path.open("a", encoding="utf-8", buffering=1) as handle:
            handle.write(line + "\n")
            handle.flush()

    def environment(self) -> dict[str, Any]:
        return environment_diagnostics(self.project_root)

    def validate_data(self) -> TrainingData:
        self._log("Validate data and load train/validation/test/catalog")
        self.data = validate_and_load_inputs(self.project_root)
        self.feature_sets = experiment_feature_sets(self.data.input_columns)
        self._log(
            f"Validated rows train={len(self.data.train):,}, "
            f"validation={len(self.data.validation):,}, test={len(self.data.test):,}; "
            f"train classes={self.data.train[TARGET_COLUMN].nunique()}, "
            f"catalog classes={len(self.data.universe_classes)}"
        )
        return self.data

    def data_summary(self) -> pd.DataFrame:
        data = self._require_data()
        records = []
        for name, frame in (
            ("train", data.train),
            ("validation", data.validation),
            ("test", data.test),
        ):
            records.append(
                {
                    "split": name,
                    "rows": len(frame),
                    "total_case_count": int(frame[WEIGHT_COLUMN].sum()),
                    "classes": int(frame[TARGET_COLUMN].nunique()),
                    "date_from": str(frame["date"].min().date()),
                    "date_to": str(frame["date"].max().date()),
                    "unsupported_classes": (
                        data.unsupported_validation
                        if name == "validation"
                        else data.unsupported_test if name == "test" else []
                    ),
                }
            )
        return pd.DataFrame(records)

    def run_baseline(self) -> dict[str, Any]:
        data = self._require_data()
        self._log("Fit hierarchical frequency baseline on train")
        baseline = fit_frequency_baseline(data.train, data.universe_classes)
        probabilities = baseline.predict_proba(data.validation)
        metrics = compute_metrics(
            data.validation[TARGET_COLUMN],
            probabilities,
            data.universe_classes,
            data.validation[WEIGHT_COLUMN],
        )
        self.baseline_payload = {
            "name": "hierarchical_train_frequency",
            "ranking_hierarchy": [
                "age_group+gender+month",
                "age_group+month",
                "month",
                "global_train_frequency",
            ],
            "evaluation_split": "validation_full_including_unsupported_classes",
            "unsupported_classes": data.unsupported_validation,
            "metrics": metrics,
        }
        weighted = metrics["case_weighted"]
        self._log(
            "Baseline validation: "
            f"Top-1={weighted['top_1_accuracy']:.4%}, "
            f"Top-3={weighted['top_3_accuracy']:.4%}, "
            f"Top-5={weighted['top_5_accuracy']:.4%}, "
            f"Top-10={weighted['top_10_accuracy']:.4%}, "
            f"log_loss={weighted['multiclass_log_loss']:.6f}"
        )
        return self.baseline_payload

    def gpu_smoke_test(self, iterations: int = 3) -> dict[str, Any]:
        data = self._require_data()
        diagnostics = self.environment()
        self._log(
            f"GPU smoke test: CatBoost {diagnostics['catboost_version']}, "
            f"detected GPUs={diagnostics['gpu_device_count']}, devices={self.config.gpu_id}"
        )
        if diagnostics["gpu_device_count"] < 1:
            raise RuntimeError(
                "CatBoost GPU smoke test aborted: no GPU detected.\n"
                + json.dumps(diagnostics, ensure_ascii=False, indent=2)
            )
        feature_columns = self.feature_sets["current_only"]
        categorical = [
            column for column in CATEGORICAL_FEATURES if column in feature_columns
        ]
        top_classes = (
            data.train.groupby(TARGET_COLUMN)[WEIGHT_COLUMN]
            .sum()
            .nlargest(2)
            .index.astype(str)
            .tolist()
        )
        smoke_rows = (
            data.train[data.train[TARGET_COLUMN].isin(top_classes)]
            .groupby(TARGET_COLUMN, group_keys=False)
            .head(256)
            .reset_index(drop=True)
        )
        features = prepare_features(smoke_rows, feature_columns)
        pool = Pool(
            features,
            label=smoke_rows[TARGET_COLUMN].astype(str),
            weight=smoke_rows[WEIGHT_COLUMN],
            cat_features=categorical,
            feature_names=feature_columns,
        )
        parameters = self.config.catboost_parameters()
        parameters.update(
            {
                "iterations": int(iterations),
                "depth": min(4, self.config.depth),
                "verbose": 1,
            }
        )
        parameters.pop("early_stopping_rounds", None)
        started = time.perf_counter()
        try:
            model = CatBoostClassifier(**parameters)
            with self.log_path.open("a", encoding="utf-8", buffering=1) as log_handle:
                tee = _TeeStream(sys.stdout, log_handle)
                model.fit(pool, log_cout=tee, log_cerr=tee)
            probability = model.predict_proba(features.head(5))
        except Exception as exc:
            failure = {
                **diagnostics,
                "smoke_test_parameters": parameters,
                "actual_catboost_error": repr(exc),
            }
            self._log(f"GPU smoke test FAILED: {exc!r}")
            raise RuntimeError(
                "CatBoost GPU smoke test failed; CPU fallback is disabled.\n"
                + json.dumps(failure, ensure_ascii=False, indent=2)
            ) from exc
        elapsed = time.perf_counter() - started
        sums = probability.sum(axis=1)
        if not np.allclose(sums, 1.0, atol=1e-8):
            raise RuntimeError(f"GPU smoke prediction probabilities do not sum to one: {sums}")
        self.smoke_result = {
            **diagnostics,
            "success": True,
            "iterations": int(iterations),
            "rows": int(len(smoke_rows)),
            "elapsed_seconds": round(elapsed, 3),
            "probability_sums": sums.tolist(),
            "task_type": "GPU",
            "devices": self.config.gpu_id,
        }
        self._log(f"GPU smoke test PASSED in {format_elapsed(elapsed)}")
        return self.smoke_result

    def train_experiment(self, experiment: str) -> dict[str, Any]:
        data = self._require_data()
        if not self.smoke_result or not self.smoke_result.get("success"):
            raise RuntimeError("GPU smoke test must pass before full experiment training")
        if experiment not in EXPERIMENT_WINDOWS:
            raise KeyError(f"Unknown experiment: {experiment}")
        if any(result["experiment"] == experiment for result in self.experiment_results):
            raise RuntimeError(f"Experiment already trained in this pipeline: {experiment}")

        feature_columns = self.feature_sets[experiment]
        categorical = [
            column for column in CATEGORICAL_FEATURES if column in feature_columns
        ]
        supported_validation = data.validation[
            ~data.validation[TARGET_COLUMN].isin(data.unsupported_validation)
        ].copy()
        train_features = prepare_features(data.train, feature_columns)
        validation_features = prepare_features(supported_validation, feature_columns)
        train_pool = Pool(
            train_features,
            label=data.train[TARGET_COLUMN].astype(str),
            weight=data.train[WEIGHT_COLUMN],
            cat_features=categorical,
            feature_names=feature_columns,
        )
        validation_pool = Pool(
            validation_features,
            label=supported_validation[TARGET_COLUMN].astype(str),
            weight=supported_validation[WEIGHT_COLUMN],
            cat_features=categorical,
            feature_names=feature_columns,
        )

        started_at = datetime.now().astimezone()
        started_clock = time.perf_counter()
        label = EXPERIMENT_LABELS[experiment]
        self._log(
            f"START {label}; features={len(feature_columns)}, train_rows={len(data.train):,}, "
            f"validation_rows={len(data.validation):,}, early_stop_supported_rows={len(supported_validation):,}"
        )
        model = CatBoostClassifier(**self.config.catboost_parameters())
        try:
            with self.log_path.open("a", encoding="utf-8", buffering=1) as log_handle:
                tee = _TeeStream(sys.stdout, log_handle)
                model.fit(
                    train_pool,
                    eval_set=validation_pool,
                    use_best_model=True,
                    log_cout=tee,
                    log_cerr=tee,
                )
        except Exception as exc:
            self._log(f"FAILED {label}: {exc!r}; CPU fallback is disabled")
            raise
        elapsed = time.perf_counter() - started_clock
        finished_at = datetime.now().astimezone()
        evaluation = evaluate_model_on_split(
            model, data, data.validation, feature_columns, "validation"
        )
        weighted = evaluation["metrics"]["case_weighted"]
        result = {
            "experiment": experiment,
            "experiment_label": label,
            "windows": list(EXPERIMENT_WINDOWS[experiment]),
            "feature_columns": feature_columns,
            "categorical_features": categorical,
            "numeric_features": [
                column for column in feature_columns if column not in categorical
            ],
            "feature_count": len(feature_columns),
            "train_rows": int(len(data.train)),
            "validation_rows": int(len(data.validation)),
            "early_stopping_validation_rows": int(len(supported_validation)),
            "started_at": started_at.isoformat(timespec="seconds"),
            "finished_at": finished_at.isoformat(timespec="seconds"),
            "elapsed_seconds": round(elapsed, 3),
            "elapsed_display": format_elapsed(elapsed),
            "best_iteration": int(model.get_best_iteration()),
            "tree_count": int(model.tree_count_),
            "validation_metrics": evaluation["metrics"],
        }
        self.models[experiment] = model
        self.experiment_results.append(result)
        candidate_path = self.project_root / f"reports/logs/{experiment}_gpu_candidate.cbm"
        model.save_model(candidate_path)
        write_json(
            self.project_root / f"reports/logs/{experiment}_gpu_result.json",
            {
                "config": asdict(self.config),
                "feature_columns": feature_columns,
                "result": result,
            },
        )
        self._log(
            f"FINISH {label}; elapsed={result['elapsed_display']}, "
            f"best_iteration={result['best_iteration']}, "
            f"Weighted Top-1={weighted['top_1_accuracy']:.4%}, "
            f"Top-3={weighted['top_3_accuracy']:.4%}, "
            f"Top-5={weighted['top_5_accuracy']:.4%}, "
            f"Top-10={weighted['top_10_accuracy']:.4%}, "
            f"log_loss={weighted['multiclass_log_loss']:.6f}"
        )
        return result

    def restore_experiment(self, experiment: str) -> dict[str, Any]:
        """Restore a completed candidate only when config and schema match exactly."""
        if not self.smoke_result or not self.smoke_result.get("success"):
            raise RuntimeError("GPU smoke test must pass before restoring an experiment")
        result_path = self.project_root / f"reports/logs/{experiment}_gpu_result.json"
        candidate_path = self.project_root / f"reports/logs/{experiment}_gpu_candidate.cbm"
        if not result_path.is_file() or not candidate_path.is_file():
            raise FileNotFoundError(f"Completed candidate is missing for {experiment}")
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        expected_features = self.feature_sets[experiment]
        if payload.get("config") != asdict(self.config):
            raise ValueError(f"Cached config differs for {experiment}")
        if payload.get("feature_columns") != expected_features:
            raise ValueError(f"Cached feature schema differs for {experiment}")
        result = payload["result"]
        if result.get("experiment") != experiment:
            raise ValueError(f"Cached experiment identity differs for {experiment}")
        model = CatBoostClassifier()
        model.load_model(candidate_path)
        self.models[experiment] = model
        self.experiment_results.append(result)
        self._log(
            f"RESTORED {result['experiment_label']}; elapsed={result['elapsed_display']}, "
            f"best_iteration={result['best_iteration']}"
        )
        return result

    def recover_experiment(self, experiment: str) -> dict[str, Any]:
        """Rebuild a sidecar from a fully saved model after an interrupted CLI."""
        data = self._require_data()
        if not self.smoke_result or not self.smoke_result.get("success"):
            raise RuntimeError("GPU smoke test must pass before recovering an experiment")
        candidate_path = self.project_root / f"reports/logs/{experiment}_gpu_candidate.cbm"
        if not candidate_path.is_file():
            raise FileNotFoundError(f"Candidate model is missing for {experiment}")
        feature_columns = self.feature_sets[experiment]
        categorical = [
            column for column in CATEGORICAL_FEATURES if column in feature_columns
        ]
        model = CatBoostClassifier()
        model.load_model(candidate_path)
        evaluation = evaluate_model_on_split(
            model, data, data.validation, feature_columns, "validation"
        )

        label = EXPERIMENT_LABELS[experiment]
        started_at: datetime | None = None
        finished_at: datetime | None = None
        for line in self.log_path.read_text(encoding="utf-8").splitlines():
            if f"] START {label};" in line:
                started_at = datetime.fromisoformat(line[1 : line.index("]")])
                finished_at = None
            elif started_at is not None and f"] FINISH {label};" in line:
                finished_at = datetime.fromisoformat(line[1 : line.index("]")])
        if started_at is None:
            raise ValueError(f"START timestamp is missing from GPU log for {experiment}")
        if finished_at is None:
            finished_at = datetime.fromtimestamp(
                candidate_path.stat().st_mtime
            ).astimezone()
        elapsed = max(0.0, (finished_at - started_at).total_seconds())
        result = {
            "experiment": experiment,
            "experiment_label": label,
            "windows": list(EXPERIMENT_WINDOWS[experiment]),
            "feature_columns": feature_columns,
            "categorical_features": categorical,
            "numeric_features": [
                column for column in feature_columns if column not in categorical
            ],
            "feature_count": len(feature_columns),
            "train_rows": int(len(data.train)),
            "validation_rows": int(len(data.validation)),
            "early_stopping_validation_rows": int(
                len(data.validation)
                - data.validation[TARGET_COLUMN].isin(data.unsupported_validation).sum()
            ),
            "started_at": started_at.isoformat(timespec="seconds"),
            "finished_at": finished_at.isoformat(timespec="seconds"),
            "elapsed_seconds": round(elapsed, 3),
            "elapsed_display": format_elapsed(elapsed),
            "best_iteration": int(model.get_best_iteration()),
            "tree_count": int(model.tree_count_),
            "validation_metrics": evaluation["metrics"],
            "recovered_from_saved_candidate": True,
        }
        self.models[experiment] = model
        self.experiment_results.append(result)
        write_json(
            self.project_root / f"reports/logs/{experiment}_gpu_result.json",
            {
                "config": asdict(self.config),
                "feature_columns": feature_columns,
                "result": result,
            },
        )
        self._log(
            f"RECOVERED {label}; elapsed={result['elapsed_display']}, "
            f"best_iteration={result['best_iteration']}"
        )
        return result

    def comparison(self) -> pd.DataFrame:
        return experiment_comparison_frame(self.experiment_results)

    def compare_and_select(self) -> tuple[dict[str, Any], pd.DataFrame]:
        data = self._require_data()
        selected, reason = select_best_experiment(self.experiment_results)
        self.selected_result = selected
        model = self.models.get(selected["experiment"])
        if model is None:
            model = CatBoostClassifier()
            model.load_model(
                self.project_root
                / f"reports/logs/{selected['experiment']}_gpu_candidate.cbm"
            )
        self.selected_model = model
        self.validation_evaluation = evaluate_model_on_split(
            model,
            data,
            data.validation,
            selected["feature_columns"],
            "validation",
        )
        self.selection_payload = {
            "selection_split": "validation",
            "test_metrics_read_or_used_for_selection": False,
            "test_rows_scored_during_selection": 0,
            "selection_rules": {
                "primary": "case_weighted_validation_top_5_accuracy_maximize",
                "top_5_near_tolerance": 0.002,
                "secondary": "case_weighted_validation_multiclass_log_loss_minimize",
                "log_loss_near_tolerance": 0.01,
                "tertiary": "fewer_features_and_weather_windows",
            },
            "selected_experiment": selected["experiment"],
            "selection_reason": reason,
            "experiments": self.comparison().to_dict("records"),
        }
        self._log(f"SELECTED {selected['experiment_label']}: {reason}")
        return selected, self.comparison()

    def save_training_checkpoint(self) -> Path:
        if self.selected_model is None or self.selection_payload is None:
            raise RuntimeError("Select the best experiment before saving a checkpoint")
        checkpoint_model = self.project_root / self.CHECKPOINT_MODEL
        self.selected_model.save_model(checkpoint_model)
        payload = {
            "config": asdict(self.config),
            "baseline": self.baseline_payload,
            "smoke_result": self.smoke_result,
            "experiment_results": self.experiment_results,
            "selection": self.selection_payload,
            "checkpoint_model": self.CHECKPOINT_MODEL,
            "test_evaluated": False,
        }
        checkpoint_state = self.project_root / self.CHECKPOINT_STATE
        write_json(checkpoint_state, payload)
        self._log(f"Saved validation-selected GPU checkpoint: {self.CHECKPOINT_MODEL}")
        return checkpoint_state

    @classmethod
    def resume_from_checkpoint(cls, project_root: Path) -> "TrainingPipeline":
        state_path = project_root.resolve() / cls.CHECKPOINT_STATE
        if not state_path.is_file():
            raise FileNotFoundError(
                f"Training checkpoint missing; run scripts/04_train_model.py first: {state_path}"
            )
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("test_evaluated"):
            raise RuntimeError(
                "This checkpoint has already been evaluated on test; refusing to score test again"
            )
        pipeline = cls(project_root, GPUTrainingConfig(**state["config"]))
        pipeline.validate_data()
        pipeline.baseline_payload = state["baseline"]
        pipeline.smoke_result = state["smoke_result"]
        pipeline.experiment_results = state["experiment_results"]
        pipeline.selection_payload = state["selection"]
        selected_name = state["selection"]["selected_experiment"]
        pipeline.selected_result = next(
            result
            for result in pipeline.experiment_results
            if result["experiment"] == selected_name
        )
        pipeline.selected_model = CatBoostClassifier()
        pipeline.selected_model.load_model(project_root / state["checkpoint_model"])
        pipeline.validation_evaluation = evaluate_model_on_split(
            pipeline.selected_model,
            pipeline.data,
            pipeline.data.validation,
            pipeline.selected_result["feature_columns"],
            "validation",
        )
        return pipeline

    def evaluate_test_once(self) -> dict[str, Any]:
        data = self._require_data()
        if self.selected_model is None or self.selected_result is None:
            raise RuntimeError("Select a model before final test evaluation")
        if self.test_payload is not None:
            raise RuntimeError("Test has already been evaluated in this pipeline instance")
        self._log("FINAL TEST evaluation starts after validation-only model selection")
        self.test_evaluation = evaluate_model_on_split(
            self.selected_model,
            data,
            data.test,
            self.selected_result["feature_columns"],
            "test",
        )
        self.test_payload = {
            "selected_experiment": self.selected_result["experiment"],
            "evaluation_split": "test_once_after_validation_selection",
            "test_used_for_selection": False,
            "unsupported_test_classes": data.unsupported_test,
            "unsupported_test_rows": int(
                data.test[TARGET_COLUMN].isin(data.unsupported_test).sum()
            ),
            "metrics": self.test_evaluation["metrics"],
        }
        weighted = self.test_payload["metrics"]["case_weighted"]
        self._log(
            f"FINAL TEST complete: Top-5={weighted['top_5_accuracy']:.4%}, "
            f"log_loss={weighted['multiclass_log_loss']:.6f}"
        )
        checkpoint_state = self.project_root / self.CHECKPOINT_STATE
        if checkpoint_state.is_file():
            state = json.loads(checkpoint_state.read_text(encoding="utf-8"))
            state["test_evaluated"] = True
            write_json(checkpoint_state, state)
        return self.test_payload

    def save_artifacts(self) -> dict[str, Path]:
        data = self._require_data()
        if self.test_payload is None or self.test_evaluation is None:
            raise RuntimeError("Evaluate the selected model on test before saving final artifacts")
        if self.selected_model is None or self.selected_result is None:
            raise RuntimeError("No selected model is available")
        if self.validation_evaluation is None or self.selection_payload is None:
            raise RuntimeError("Validation selection artifacts are incomplete")

        models_dir = self.project_root / "models"
        metrics_dir = self.project_root / "reports/metrics"
        models_dir.mkdir(parents=True, exist_ok=True)
        metrics_dir.mkdir(parents=True, exist_ok=True)
        model_path = models_dir / "weather_disease_catboost_v2.cbm"

        sample_source = data.test.dropna(
            subset=self.selected_result["feature_columns"]
        ).head(3)
        sample_features = prepare_features(
            sample_source, self.selected_result["feature_columns"]
        )
        before = self.selected_model.predict_proba(sample_features)
        self.selected_model.save_model(model_path)
        reloaded = CatBoostClassifier()
        reloaded.load_model(model_path)
        after = reloaded.predict_proba(sample_features)
        maximum_difference = float(np.max(np.abs(before - after)))
        if maximum_difference > 1e-12:
            raise RuntimeError(
                f"Prediction changed after final model save/load: {maximum_difference}"
            )
        model_classes = [str(value) for value in reloaded.classes_]
        class_records = self._class_records(model_classes)

        feature_schema = {
            "selected_experiment": self.selected_result["experiment"],
            "feature_columns": self.selected_result["feature_columns"],
            "categorical_features": self.selected_result["categorical_features"],
            "numeric_features": self.selected_result["numeric_features"],
            "target_column": TARGET_COLUMN,
            "weight_column": WEIGHT_COLUMN,
            "excluded_columns": sorted(EXCLUDED_FEATURE_COLUMNS),
            "weather_windows_days": self.selected_result["windows"],
        }
        class_mapping = {
            "model_classes": model_classes,
            "model_class_count": len(model_classes),
            "catalog_class_count": len(data.universe_classes),
            "classes": class_records,
        }
        model_metadata = {
            "model_type": "CatBoostClassifier",
            "model_format": "CatBoost cbm",
            "model_path": relative_posix(model_path, self.project_root),
            "model_sha256": sha256_file(model_path),
            "device": "GPU",
            "gpu_id": self.config.gpu_id,
            "environment": self.environment(),
            "gpu_smoke_test": self.smoke_result,
            "selected_experiment": self.selected_result["experiment"],
            "catboost_parameters": self.config.catboost_parameters(),
            "best_iteration": self.selected_result["best_iteration"],
            "tree_count": self.selected_result["tree_count"],
            "model_class_count": len(model_classes),
            "catalog_class_count": len(data.universe_classes),
            "train_rows": int(len(data.train)),
            "train_total_case_count": int(data.train[WEIGHT_COLUMN].sum()),
            "validation_rows": int(len(data.validation)),
            "validation_total_case_count": int(data.validation[WEIGHT_COLUMN].sum()),
            "test_rows": int(len(data.test)),
            "test_total_case_count": int(data.test[WEIGHT_COLUMN].sum()),
            "test_used_for_selection": False,
            "experiment_timings": [
                {
                    key: result[key]
                    for key in (
                        "experiment",
                        "started_at",
                        "finished_at",
                        "elapsed_seconds",
                        "elapsed_display",
                        "best_iteration",
                    )
                }
                for result in self.experiment_results
            ],
            "serialization_check": {
                "maximum_absolute_probability_difference": maximum_difference,
                "sample_input": sample_features.to_dict("records"),
                "expected_probabilities": before.tolist(),
            },
        }

        write_json(models_dir / "feature_schema.json", feature_schema)
        write_json(models_dir / "class_mapping.json", class_mapping)
        write_json(models_dir / "model_selection.json", self.selection_payload)
        write_json(models_dir / "model_metadata.json", model_metadata)
        write_json(metrics_dir / "baseline_metrics.json", self.baseline_payload)
        comparison = self.comparison()
        write_csv(metrics_dir / "experiment_comparison.csv", comparison)
        validation_payload = {
            "selected_experiment": self.selected_result["experiment"],
            "evaluation_split": "validation_full_including_unsupported_classes",
            "unsupported_validation_classes": data.unsupported_validation,
            "metrics": self.validation_evaluation["metrics"],
        }
        write_json(metrics_dir / "validation_metrics.json", validation_payload)
        write_json(metrics_dir / "test_metrics.json", self.test_payload)

        validation_per_class = self.validation_evaluation["per_class"]
        test_columns = [
            TARGET_COLUMN,
            "test_support_rows",
            "test_support_case_count",
            "test_recall_top_1",
            "test_recall_top_5",
        ]
        combined = validation_per_class.merge(
            self.test_evaluation["per_class"][test_columns],
            on=TARGET_COLUMN,
            how="outer",
            validate="one_to_one",
        )
        write_csv(metrics_dir / "per_class_metrics.csv", combined)
        write_training_report(
            self.project_root,
            data,
            self.baseline_payload,
            comparison,
            validation_payload,
            self.test_payload,
            self.selection_payload,
            combined,
        )
        self.final_verification = {
            "model_load_success": True,
            "probability_sums": after.sum(axis=1).tolist(),
            "maximum_absolute_probability_difference": maximum_difference,
            "model_class_count": len(model_classes),
            "class_mapping_count": len(class_mapping["model_classes"]),
        }
        self._log(
            f"Saved final GPU model and reports; serialization max diff={maximum_difference:.3e}"
        )
        return {
            "model": model_path,
            "metadata": models_dir / "model_metadata.json",
            "report": self.project_root / "reports/MODEL_TRAINING_REPORT.md",
        }

    def verify_final_artifacts(self, sample_rows: int = 5) -> dict[str, Any]:
        data = self._require_data()
        feature_schema = json.loads(
            (self.project_root / "models/feature_schema.json").read_text(encoding="utf-8")
        )
        class_mapping = json.loads(
            (self.project_root / "models/class_mapping.json").read_text(encoding="utf-8")
        )
        model = CatBoostClassifier()
        model.load_model(self.project_root / "models/weather_disease_catboost_v2.cbm")
        features = prepare_features(
            data.test.head(sample_rows), feature_schema["feature_columns"]
        )
        probability = model.predict_proba(features)
        model_classes = [str(value) for value in model.classes_]
        result = {
            "model_load_success": True,
            "sample_rows": int(len(features)),
            "probability_sums": probability.sum(axis=1).tolist(),
            "probabilities_sum_to_one": bool(
                np.allclose(probability.sum(axis=1), 1.0, atol=1e-10)
            ),
            "class_mapping_matches": model_classes == class_mapping["model_classes"],
            "model_class_count": len(model_classes),
        }
        if not result["probabilities_sum_to_one"] or not result["class_mapping_matches"]:
            raise RuntimeError(f"Final model verification failed: {result}")
        self.final_verification = result
        self._log(f"Final model verification PASSED: {result}")
        return result

    def _class_records(self, model_classes: list[str]) -> list[dict[str, Any]]:
        data = self._require_data()
        lookup = (
            data.catalog.drop_duplicates(TARGET_COLUMN, keep="first")
            .set_index(TARGET_COLUMN)
            .to_dict("index")
        )
        model_index = {label: index for index, label in enumerate(model_classes)}
        records = []
        for label in data.universe_classes:
            details = lookup.get(label, {})
            records.append(
                {
                    "disease_group_id": label,
                    "disease_group_name": str(details.get("disease_group_name", "")),
                    "report_group_code": (
                        None
                        if pd.isna(details.get("report_group_code"))
                        else str(details.get("report_group_code"))
                    ),
                    "support_level": str(details.get("support_level", "")),
                    "model_supported": label in model_index,
                    "model_class_index": model_index.get(label),
                }
            )
        return records

    def _require_data(self) -> TrainingData:
        if self.data is None:
            raise RuntimeError("Call validate_data() before this pipeline step")
        return self.data


def run_training_stage(
    project_root: Path, config: GPUTrainingConfig | None = None
) -> TrainingPipeline:
    pipeline = TrainingPipeline(project_root, config)
    pipeline.validate_data()
    pipeline.run_baseline()
    pipeline.gpu_smoke_test()
    for experiment in EXPERIMENT_WINDOWS:
        result_path = project_root / f"reports/logs/{experiment}_gpu_result.json"
        candidate_path = project_root / f"reports/logs/{experiment}_gpu_candidate.cbm"
        if result_path.is_file() and candidate_path.is_file():
            pipeline.restore_experiment(experiment)
        elif candidate_path.is_file():
            pipeline.recover_experiment(experiment)
        else:
            pipeline.train_experiment(experiment)
    pipeline.compare_and_select()
    pipeline.save_training_checkpoint()
    return pipeline


def run_evaluation_stage(project_root: Path) -> TrainingPipeline:
    pipeline = TrainingPipeline.resume_from_checkpoint(project_root)
    pipeline.evaluate_test_once()
    pipeline.save_artifacts()
    pipeline.verify_final_artifacts()
    return pipeline


def run_full_pipeline(
    project_root: Path, config: GPUTrainingConfig | None = None
) -> TrainingPipeline:
    pipeline = TrainingPipeline(project_root, config)
    pipeline.validate_data()
    pipeline.run_baseline()
    pipeline.gpu_smoke_test()
    for experiment in EXPERIMENT_WINDOWS:
        pipeline.train_experiment(experiment)
    pipeline.compare_and_select()
    pipeline.evaluate_test_once()
    pipeline.save_artifacts()
    pipeline.verify_final_artifacts()
    return pipeline
