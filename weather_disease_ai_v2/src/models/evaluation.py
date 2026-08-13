"""Validation comparison, best-model selection, and final test evaluation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
from catboost import CatBoostClassifier

from src.models.common import (
    TARGET_COLUMN,
    WEIGHT_COLUMN,
    TrainingData,
    environment_diagnostics,
    prepare_features,
)
from src.models.metrics import compute_metrics, expand_probabilities, per_class_metrics


TOP5_NEAR_TOLERANCE = 0.002
LOG_LOSS_NEAR_TOLERANCE = 0.01


def flatten_metrics(prefix: str, metrics: dict[str, dict[str, float]]) -> dict[str, float]:
    return {
        f"{prefix}_{version}_{name}": float(value)
        for version, values in metrics.items()
        for name, value in values.items()
    }


def experiment_comparison_frame(results: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "experiment": result["experiment"],
                "experiment_label": result["experiment_label"],
                "windows": "+".join(map(str, result["windows"])),
                "feature_count": result["feature_count"],
                "train_rows": result["train_rows"],
                "validation_rows": result["validation_rows"],
                "started_at": result["started_at"],
                "finished_at": result["finished_at"],
                "training_seconds": result["elapsed_seconds"],
                "best_iteration": result["best_iteration"],
                "tree_count": result["tree_count"],
                **flatten_metrics("validation", result["validation_metrics"]),
            }
            for result in results
        ]
    )


def select_best_experiment(results: list[dict[str, Any]]) -> tuple[dict[str, Any], str]:
    if len(results) != 4:
        raise ValueError(f"Expected four completed experiments, received {len(results)}")
    max_top5 = max(
        result["validation_metrics"]["case_weighted"]["top_5_accuracy"]
        for result in results
    )
    near_top5 = [
        result
        for result in results
        if max_top5
        - result["validation_metrics"]["case_weighted"]["top_5_accuracy"]
        <= TOP5_NEAR_TOLERANCE
    ]
    minimum_log_loss = min(
        result["validation_metrics"]["case_weighted"]["multiclass_log_loss"]
        for result in near_top5
    )
    near_log_loss = [
        result
        for result in near_top5
        if result["validation_metrics"]["case_weighted"]["multiclass_log_loss"]
        - minimum_log_loss
        <= LOG_LOSS_NEAR_TOLERANCE
    ]
    selected = min(
        near_log_loss,
        key=lambda result: (result["feature_count"], len(result["windows"])),
    )
    reason = (
        "Selected only from full-validation metrics: maximize case-weighted Top-5; "
        f"within {TOP5_NEAR_TOLERANCE:.3f} prefer lower case-weighted log loss; "
        f"within {LOG_LOSS_NEAR_TOLERANCE:.3f} prefer fewer features/windows. "
        "No test prediction or test metric was used."
    )
    return selected, reason


def evaluate_model_on_split(
    model: CatBoostClassifier,
    data: TrainingData,
    frame: pd.DataFrame,
    feature_columns: list[str],
    split_name: str,
) -> dict[str, Any]:
    features = prepare_features(frame, feature_columns)
    model_probabilities = model.predict_proba(features)
    model_classes = [str(value) for value in model.classes_]
    probabilities = expand_probabilities(
        model_probabilities, model_classes, data.universe_classes
    )
    metrics = compute_metrics(
        frame[TARGET_COLUMN], probabilities, data.universe_classes, frame[WEIGHT_COLUMN]
    )
    classes = per_class_metrics(
        data.train,
        frame,
        probabilities,
        data.universe_classes,
        data.catalog,
        split_name,
    )
    return {
        "metrics": metrics,
        "probabilities": probabilities,
        "model_probabilities": model_probabilities,
        "model_classes": model_classes,
        "per_class": classes,
    }


def _metric_text(metrics: dict[str, dict[str, float]], version: str, name: str) -> str:
    value = metrics[version][name]
    if name == "multiclass_log_loss":
        return f"{value:.6f}"
    return f"{value:.4%}"


def _experiment_markdown(comparison: pd.DataFrame) -> list[str]:
    columns = [
        "experiment",
        "feature_count",
        "best_iteration",
        "training_seconds",
        "validation_case_weighted_top_5_accuracy",
        "validation_case_weighted_multiclass_log_loss",
        "validation_unweighted_top_5_accuracy",
    ]
    lines = [
        "| Experiment | Features | Best iteration | Time (s) | Weighted Top-5 | Weighted log loss | Unweighted Top-5 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for _, row in comparison[columns].iterrows():
        lines.append(
            f"| {row['experiment']} | {int(row['feature_count'])} | {int(row['best_iteration'])} "
            f"| {row['training_seconds']:.2f} "
            f"| {row['validation_case_weighted_top_5_accuracy']:.4%} "
            f"| {row['validation_case_weighted_multiclass_log_loss']:.6f} "
            f"| {row['validation_unweighted_top_5_accuracy']:.4%} |"
        )
    return lines


def _group_lines(frame: pd.DataFrame, heading: str) -> list[str]:
    lines = [f"### {heading}", ""]
    if frame.empty:
        return [*lines, "- Không có."]
    for _, row in frame.iterrows():
        lines.append(
            f"- `{row['disease_group_id']}` — {row['disease_group_name']}: "
            f"Test Top-5 recall {row['test_recall_top_5']:.2%}, "
            f"support {int(row['test_support_case_count']):,} lượt."
        )
    return lines


def write_training_report(
    project_root: Path,
    data: Any,
    baseline: dict[str, Any],
    comparison: pd.DataFrame,
    validation_metrics: dict[str, Any],
    test_metrics: dict[str, Any],
    selection: dict[str, Any],
    per_class: pd.DataFrame,
) -> None:
    supported_test = per_class[
        per_class["model_supported"]
        & (per_class["test_support_case_count"] > 0)
        & per_class["test_recall_top_5"].notna()
    ].copy()
    best_groups = supported_test.sort_values(
        ["test_recall_top_5", "test_support_case_count"],
        ascending=[False, False],
        kind="mergesort",
    ).head(5)
    worst_groups = supported_test.sort_values(
        ["test_recall_top_5", "test_support_case_count"],
        ascending=[True, False],
        kind="mergesort",
    ).head(5)
    selected = selection["selected_experiment"]
    selected_row = comparison[comparison["experiment"] == selected].iloc[0]
    baseline_metrics = baseline["metrics"]
    validation = validation_metrics["metrics"]
    test = test_metrics["metrics"]
    environment = environment_diagnostics(project_root)

    unsupported_union = sorted(
        set(data.unsupported_validation) | set(data.unsupported_test)
    )
    lines = [
        "# Model Training Report",
        "",
        "Giai đoạn này chỉ huấn luyện và đánh giá offline; không thay đổi backend, API hoặc frontend.",
        "",
        "> Điểm xếp hạng các nhóm bệnh thường được ghi nhận trong những trường hợp có tuổi, giới tính và điều kiện thời tiết tương tự.",
        "",
        "Kết quả không phải xác suất chắc chắn trẻ mắc bệnh và không phải chẩn đoán y khoa.",
        "",
        "## Môi trường GPU",
        "",
        f"- CatBoost: `{environment['catboost_version']}`.",
        f"- GPU CatBoost nhận diện: `{environment['gpu_device_count']}`; cấu hình bắt buộc `task_type=GPU`, `devices=0`.",
        f"- `nvidia-smi`: `{environment['nvidia_smi']}`.",
        "- GPU smoke test đã chạy thành công trước mọi experiment; pipeline không có nhánh fallback CPU.",
        "",
        "## Dữ liệu",
        "",
        "| Tập | Dòng | Tổng case_count | Khoảng ngày |",
        "|---|---:|---:|---|",
        f"| Train | {len(data.train):,} | {int(data.train[WEIGHT_COLUMN].sum()):,} | {data.train['date'].min().date()} – {data.train['date'].max().date()} |",
        f"| Validation | {len(data.validation):,} | {int(data.validation[WEIGHT_COLUMN].sum()):,} | {data.validation['date'].min().date()} – {data.validation['date'].max().date()} |",
        f"| Test | {len(data.test):,} | {int(data.test[WEIGHT_COLUMN].sum()):,} | {data.test['date'].min().date()} – {data.test['date'].max().date()} |",
        "",
        f"- Số lớp model học được: {data.train[TARGET_COLUMN].nunique():,}.",
        f"- Số lớp toàn catalog: {len(data.universe_classes):,}.",
        f"- Lớp unsupported trong validation: {', '.join(data.unsupported_validation) or 'không có'}.",
        f"- Lớp unsupported trong test: {', '.join(data.unsupported_test) or 'không có'}.",
        f"- Tổng hợp lớp unsupported: {', '.join(unsupported_union) or 'không có'}.",
        "",
        "Các lớp unsupported vẫn được tính trong metric toàn tập như các trường hợp model không thể xếp đúng. Chúng không được đưa vào `eval_set` early stopping vì CatBoost chưa học các nhãn này.",
        "",
        "## Baseline tần suất trên validation",
        "",
        "Baseline dùng lần lượt `age_group + gender + month`, `age_group + month`, `month`, rồi tần suất toàn train.",
        "",
        f"- Weighted Top-1/3/5/10: {_metric_text(baseline_metrics, 'case_weighted', 'top_1_accuracy')} / {_metric_text(baseline_metrics, 'case_weighted', 'top_3_accuracy')} / {_metric_text(baseline_metrics, 'case_weighted', 'top_5_accuracy')} / {_metric_text(baseline_metrics, 'case_weighted', 'top_10_accuracy')}.",
        f"- Weighted log loss: {_metric_text(baseline_metrics, 'case_weighted', 'multiclass_log_loss')}.",
        f"- Weighted-sample Macro F1 / Weighted F1: {_metric_text(baseline_metrics, 'case_weighted', 'macro_f1')} / {_metric_text(baseline_metrics, 'case_weighted', 'weighted_f1')}.",
        f"- Unweighted Top-5: {_metric_text(baseline_metrics, 'unweighted', 'top_5_accuracy')}.",
        "",
        "## Bốn experiment CatBoost trên validation",
        "",
        *_experiment_markdown(comparison),
        "",
        "## Model được chọn",
        "",
        f"- Experiment: `{selected}` ({int(selected_row['feature_count'])} features).",
        f"- Lý do: {selection['selection_reason']}",
        "- Test không được dự đoán hoặc dùng trong quá trình chọn model.",
        f"- Validation weighted Top-5: {_metric_text(validation, 'case_weighted', 'top_5_accuracy')}.",
        f"- Validation weighted log loss: {_metric_text(validation, 'case_weighted', 'multiclass_log_loss')}.",
        "",
        "## Đánh giá test một lần sau khi chọn",
        "",
        f"- Weighted Top-1/3/5/10: {_metric_text(test, 'case_weighted', 'top_1_accuracy')} / {_metric_text(test, 'case_weighted', 'top_3_accuracy')} / {_metric_text(test, 'case_weighted', 'top_5_accuracy')} / {_metric_text(test, 'case_weighted', 'top_10_accuracy')}.",
        f"- Weighted log loss: {_metric_text(test, 'case_weighted', 'multiclass_log_loss')}.",
        f"- Weighted-sample Macro F1 / Weighted F1: {_metric_text(test, 'case_weighted', 'macro_f1')} / {_metric_text(test, 'case_weighted', 'weighted_f1')}.",
        f"- Unweighted Top-1/3/5/10: {_metric_text(test, 'unweighted', 'top_1_accuracy')} / {_metric_text(test, 'unweighted', 'top_3_accuracy')} / {_metric_text(test, 'unweighted', 'top_5_accuracy')} / {_metric_text(test, 'unweighted', 'top_10_accuracy')}.",
        f"- Unweighted log loss: {_metric_text(test, 'unweighted', 'multiclass_log_loss')}.",
        "",
        "## Nhóm bệnh tốt nhất và kém nhất",
        "",
        *_group_lines(best_groups, "Top 5 tốt nhất trong các lớp supported có mặt ở test"),
        "",
        *_group_lines(worst_groups, "Top 5 kém nhất trong các lớp supported có mặt ở test"),
        "",
        "## Hạn chế",
        "",
        "- Dữ liệu mất cân bằng mạnh; model chính không bật cân bằng lớp theo yêu cầu, nên nhóm nhiều lượt có ảnh hưởng lớn hơn.",
        "- Nhóm `low` và `insufficient` có recall biến động và không nên được diễn giải như độ tin cậy y khoa.",
        "- Các lớp unsupported không thể được model dự đoán vì không có trong train.",
        "- Đây là xếp hạng thống kê trên các ca đã ghi nhận, không đo quan hệ nhân quả giữa thời tiết và bệnh.",
        "- Các cửa sổ đầu chuỗi có giá trị thiếu khi chưa đủ lịch sử; CatBoost xử lý trực tiếp giá trị số thiếu.",
        "",
        "## File đã tạo hoặc chỉnh sửa",
        "",
        "- `requirements.txt`",
        "- `src/models/__init__.py`",
        "- `src/models/common.py`",
        "- `src/models/baseline.py`",
        "- `src/models/metrics.py`",
        "- `src/models/training.py`",
        "- `src/models/evaluation.py`",
        "- `scripts/04_train_model.py`",
        "- `scripts/05_evaluate_model.py`",
        "- `notebooks/01_train_weather_disease_catboost_v2.ipynb`",
        "- `tests/test_gpu_pipeline_structure.py`",
        "- `tests/test_model_artifacts.py`",
        "- `models/weather_disease_catboost_v2.cbm`",
        "- `models/model_metadata.json`",
        "- `models/feature_schema.json`",
        "- `models/class_mapping.json`",
        "- `models/model_selection.json`",
        "- `reports/metrics/baseline_metrics.json`",
        "- `reports/metrics/experiment_comparison.csv`",
        "- `reports/metrics/validation_metrics.json`",
        "- `reports/metrics/test_metrics.json`",
        "- `reports/metrics/per_class_metrics.csv`",
        "- `reports/logs/training_gpu.log`",
        "- `reports/MODEL_TRAINING_REPORT.md`",
        "",
        "## Lệnh và test",
        "",
        "```bash",
        "python scripts/04_train_model.py",
        "python scripts/05_evaluate_model.py",
        "pytest",
        "```",
        "",
        "Các test artifact kiểm tra load model, số lớp output, tổng xác suất, ánh xạ Top-K, feature leakage, selection không dùng test và độ ổn định trước/sau serialization.",
        "",
        "Project cũ, backend, API và frontend không bị chỉnh sửa.",
    ]
    (project_root / "reports/MODEL_TRAINING_REPORT.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
