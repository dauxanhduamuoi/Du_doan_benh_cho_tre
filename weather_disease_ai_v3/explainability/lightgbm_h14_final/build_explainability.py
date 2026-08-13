"""Recreate, persist, reproduce, then explain the locked final H14 weather OVR model."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


EXPLAIN_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = EXPLAIN_DIR.parents[1]
DEPLOY_DIR = PROJECT_ROOT / "deployment/lightgbm_h14_weather"
MODELS_DIR = DEPLOY_DIR / "models"
FIGURES_DIR = EXPLAIN_DIR / "figures"
LOGS_DIR = EXPLAIN_DIR / "logs"
RUNTIME_DEPS = EXPLAIN_DIR / "runtime_deps"
BENCHMARK_RUNTIME = (
    PROJECT_ROOT / "benchmarks/lightgbm_ovr_h3_h7_h14/artifacts/runtime_deps"
)
for path in (RUNTIME_DEPS, BENCHMARK_RUNTIME):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import lightgbm as lgb
from lightgbm import LGBMClassifier


FINAL_DIR = PROJECT_ROOT / "final_test/lightgbm_ovr_h3_h7_h14"
FINAL_SCRIPT = FINAL_DIR / "run_final_test.py"
FINAL_CONFIG = FINAL_DIR / "config_locked.json"
FINAL_SCORES = FINAL_DIR / "scores/h14_with_weather.npy"
FINAL_SCORE_CONTRACT = FINAL_DIR / "model_metadata/score_contract.json"
FINAL_CATEGORY_MAPPINGS = FINAL_DIR / "model_metadata/category_mappings.json"
FINAL_BEST_ITERATIONS = FINAL_DIR / "model_metadata/best_iterations_locked.csv"
FINAL_MARKER = FINAL_DIR / "logs/TEST_OPENED_ONCE.lock"
DISEASE_CATALOG = PROJECT_ROOT / "data/processed/disease_catalog.csv"
EVENT_LOG = LOGS_DIR / "explainability_log.jsonl"
REPORT_PATH = EXPLAIN_DIR / "EXPLAINABILITY_REPORT.md"

SHAP_SAMPLE_SIZE = 512
RANDOM_SEED = 42
REPRO_MAX_ABS_TOLERANCE = 1e-7
REPRO_RMSE_TOLERANCE = 1e-8
SHAP_ADDITIVITY_TOLERANCE = 1e-6


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def event(name: str, **details: Any) -> None:
    record = {
        "event": name,
        "time_local": time.strftime("%Y-%m-%d %H:%M:%S"),
        **details,
    }
    with EVENT_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(json.dumps(record, ensure_ascii=False), flush=True)


def load_final_module() -> Any:
    spec = importlib.util.spec_from_file_location("locked_final_protocol", FINAL_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load locked final protocol")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def snapshot_tree(path: Path) -> dict[str, str]:
    return {
        str(item.relative_to(path)).replace("\\", "/"): sha256_file(item)
        for item in sorted(path.rglob("*"))
        if item.is_file() and "__pycache__" not in item.parts
    }


def feature_group(feature: str) -> str:
    if feature in {"age_group", "gender"}:
        return "DEMOGRAPHIC"
    if feature in {"month", "season", "day_of_year_sin", "day_of_year_cos"}:
        return "SEASONAL_CALENDAR"
    if feature.endswith("_current"):
        return "WEATHER_CURRENT"
    if feature.endswith("_3d"):
        return "WEATHER_3D"
    if feature.endswith("_7d"):
        return "WEATHER_7D"
    raise RuntimeError(f"Unmapped locked feature: {feature}")


def weather_variable(feature: str) -> str:
    lower = feature.lower()
    if "temperature" in lower:
        return "TEMPERATURE"
    if "humidity" in lower:
        return "HUMIDITY"
    if "rain" in lower or "precipitation" in lower:
        return "RAIN_PRECIPITATION"
    if "wind" in lower:
        return "WIND"
    if "weather_code" in lower:
        return "WEATHER_CODE"
    return "OTHER_WEATHER"


def human_label(feature: str) -> str:
    if feature in {"day_of_year_sin", "day_of_year_cos"}:
        return "Thời điểm trong năm"
    if feature == "month":
        return "Yếu tố mùa vụ theo tháng"
    if feature == "season":
        return "Mùa mưa / mùa khô"
    if feature == "age_group":
        return "Nhóm tuổi"
    if feature == "gender":
        return "Giới tính"
    variable = {
        "TEMPERATURE": "Nhiệt độ",
        "HUMIDITY": "Độ ẩm",
        "RAIN_PRECIPITATION": "Lượng mưa",
        "WIND": "Gió",
        "WEATHER_CODE": "Trạng thái thời tiết",
        "OTHER_WEATHER": "Thời tiết",
    }[weather_variable(feature)]
    window = (
        "hiện tại"
        if feature.endswith("_current")
        else "3 ngày gần đây"
        if feature.endswith("_3d")
        else "7 ngày gần đây"
    )
    return f"{variable} — {window}"


def safe_disease_filename(disease_id: str) -> str:
    if not disease_id or any(character not in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_-" for character in disease_id):
        raise RuntimeError(f"Unsafe disease ID for model filename: {disease_id!r}")
    return f"disease_{disease_id}.txt"


def model_params(config: dict[str, Any], n_estimators: int) -> dict[str, Any]:
    params = dict(config["classifier"])
    params["n_estimators"] = int(n_estimators)
    forbidden = {"class_weight", "scale_pos_weight"} & set(params)
    if forbidden:
        raise RuntimeError(f"Forbidden model parameters: {sorted(forbidden)}")
    return params


def load_booster(model_path: Path) -> lgb.Booster:
    """Load native LightGBM text through Python to support the Unicode workspace path."""
    return lgb.Booster(model_str=model_path.read_text(encoding="utf-8"))


def normalize(values: np.ndarray) -> np.ndarray:
    total = float(values.sum())
    return values / total if total > 0 else np.zeros_like(values, dtype=np.float64)


def extract_shap_values(explainer: Any, features: pd.DataFrame) -> tuple[np.ndarray, float]:
    values = explainer.shap_values(features, check_additivity=True)
    if isinstance(values, list):
        values = values[-1]
    array = np.asarray(values, dtype=np.float64)
    if array.ndim == 3:
        array = array[:, :, -1]
    expected = explainer.expected_value
    expected_array = np.asarray(expected, dtype=np.float64).reshape(-1)
    base = float(expected_array[-1])
    return array, base


def explain_query(
    query_features: pd.DataFrame,
    raw_query: pd.Series,
    manifest: list[dict[str, Any]],
    disease_names: dict[str, str],
    top_k: int = 5,
) -> list[dict[str, Any]]:
    import shap

    scores: list[float] = []
    boosters: list[lgb.Booster] = []
    for item in manifest:
        booster = load_booster(DEPLOY_DIR / item["model_path"])
        boosters.append(booster)
        scores.append(float(booster.predict(query_features)[0]))
    order = np.argsort(-np.asarray(scores), kind="stable")[:top_k]
    result: list[dict[str, Any]] = []
    feature_names = query_features.columns.tolist()
    for rank, model_index in enumerate(order, start=1):
        item = manifest[int(model_index)]
        explainer = shap.TreeExplainer(
            boosters[int(model_index)],
            model_output="raw",
            feature_perturbation="tree_path_dependent",
        )
        values, _ = extract_shap_values(explainer, query_features)
        row_values = values[0]
        positive_indices = np.flatnonzero(row_values > 0)
        negative_indices = np.flatnonzero(row_values < 0)
        positive_indices = positive_indices[np.argsort(-row_values[positive_indices])][:5]
        negative_indices = negative_indices[np.argsort(row_values[negative_indices])][:5]

        def describe(indices: np.ndarray) -> list[dict[str, Any]]:
            records: list[dict[str, Any]] = []
            for index in indices:
                feature = feature_names[int(index)]
                actual_value = raw_query[feature]
                if isinstance(actual_value, np.generic):
                    actual_value = actual_value.item()
                records.append(
                    {
                        "feature": feature,
                        "human_label": human_label(feature),
                        "actual_value": actual_value,
                        "shap_value": float(row_values[int(index)]),
                        "human_group": feature_group(feature),
                    }
                )
            return records

        disease_id = str(item["disease_id"])
        result.append(
            {
                "query_id": str(raw_query["query_id"]),
                "rank": rank,
                "disease_id": disease_id,
                "disease_name": disease_names.get(disease_id, ""),
                "ranking_score": scores[int(model_index)],
                "score_interpretation": "locked model ranking score; not a clinical diagnosis",
                "top_positive_features": json.dumps(describe(positive_indices), ensure_ascii=False),
                "top_negative_features": json.dumps(describe(negative_indices), ensure_ascii=False),
            }
        )
    return result


def create_figures(
    feature_frame: pd.DataFrame,
    group_frame: pd.DataFrame,
    comparison_frame: pd.DataFrame,
    local_frame: pd.DataFrame,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.style.use("seaborn-v0_8-whitegrid")

    top = feature_frame.nsmallest(20, "rank").sort_values("normalized_importance")
    fig, ax = plt.subplots(figsize=(10, 7))
    ax.barh(top["feature"], top["normalized_importance"], color="#2F6B8A")
    ax.set_title("Top-20 global SHAP features (macro-normalized)")
    ax.set_xlabel("Relative SHAP contribution")
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "01_top20_global_shap.png", dpi=160)
    plt.close(fig)

    group = group_frame.sort_values("relative_importance")
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.barh(group["feature_group"], group["relative_importance"], color="#4C956C")
    ax.set_title("Feature-group relative SHAP contribution")
    ax.set_xlabel("Relative SHAP contribution")
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "02_feature_group_importance.png", dpi=160)
    plt.close(fig)

    totals = comparison_frame[comparison_frame["category_type"] == "TOTAL"]
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.bar(totals["category"], totals["relative_importance"], color=["#6C5B7B", "#2F6B8A", "#F28E2B"])
    ax.set_title("Seasonal vs Weather vs Demographic")
    ax.set_ylabel("Relative SHAP contribution")
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "03_seasonal_vs_weather.png", dpi=160)
    plt.close(fig)

    windows = comparison_frame[comparison_frame["category_type"] == "WEATHER_WINDOW"]
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.bar(windows["category"], windows["relative_importance"], color="#5DA5DA")
    ax.set_title("Weather contribution by window")
    ax.set_ylabel("Relative SHAP contribution")
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "04_weather_windows.png", dpi=160)
    plt.close(fig)

    variables = comparison_frame[comparison_frame["category_type"] == "WEATHER_VARIABLE"].sort_values("relative_importance")
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.barh(variables["category"], variables["relative_importance"], color="#59A14F")
    ax.set_title("Weather contribution by variable family")
    ax.set_xlabel("Relative SHAP contribution")
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "05_weather_variables.png", dpi=160)
    plt.close(fig)

    first = local_frame.iloc[0]
    positive = json.loads(first["top_positive_features"])
    negative = json.loads(first["top_negative_features"])
    records = positive + negative
    labels = [item["human_label"] for item in records]
    values = [item["shap_value"] for item in records]
    colors = ["#2E8B57" if value > 0 else "#C44E52" for value in values]
    order = np.argsort(values)
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.barh([labels[index] for index in order], [values[index] for index in order], color=[colors[index] for index in order])
    ax.axvline(0, color="black", linewidth=0.8)
    ax.set_title(f"Local SHAP — {first['disease_id']} (rank {first['rank']})")
    ax.set_xlabel("SHAP contribution to raw model score")
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "06_local_explanation_example.png", dpi=160)
    plt.close(fig)


def write_report(
    feature_frame: pd.DataFrame,
    group_frame: pd.DataFrame,
    comparison_frame: pd.DataFrame,
    disease_frame: pd.DataFrame,
    local_frame: pd.DataFrame,
    reproduction: dict[str, Any],
    additivity: dict[str, Any],
    runtime_seconds: float,
) -> None:
    group = group_frame.set_index("feature_group")["relative_importance"]
    totals = comparison_frame[comparison_frame["category_type"] == "TOTAL"].set_index("category")["relative_importance"]
    windows = comparison_frame[comparison_frame["category_type"] == "WEATHER_WINDOW"].set_index("category")["relative_importance"]
    weather_variables = comparison_frame[comparison_frame["category_type"] == "WEATHER_VARIABLE"].sort_values("relative_importance", ascending=False)
    top_features = feature_frame.nsmallest(10, "rank")
    weather_heavy = disease_frame.nlargest(5, "weather_importance")
    seasonal_heavy = disease_frame.nlargest(5, "seasonal_importance")
    local = local_frame.iloc[0]
    positive = json.loads(local["top_positive_features"])
    negative = json.loads(local["top_negative_features"])
    lines = [
        "# Explainability Report — Final LightGBM OVR H14 WITH WEATHER",
        "",
        "## 1. Locked model and reproduction",
        "",
        "- 221 per-disease LightGBM boosters were recreated from the locked TRAIN+VALIDATION protocol and persisted before reproduction.",
        "- No TEST target was loaded. TEST features were used only to compare the recreated scores with the already saved final score matrix.",
        f"- **{reproduction['decision']}**: max abs diff={reproduction['max_absolute_difference']:.12g}, "
        f"mean abs diff={reproduction['mean_absolute_difference']:.12g}, RMSE={reproduction['rmse']:.12g}.",
        f"- Ordered Top-5 agreement={reproduction['top5_agreement']:.6f}; Top-10 agreement={reproduction['top10_agreement']:.6f}.",
        "",
        "## 2. Global SHAP method",
        "",
        f"`shap.TreeExplainer` with `model_output=raw` was evaluated on a deterministic {SHAP_SAMPLE_SIZE}-query sample from TRAIN+VALIDATION. "
        "For each disease, mean(|SHAP|) was normalized to sum to one, then macro-averaged across 221 diseases so common diseases could not dominate the summary.",
        "",
        "SHAP explains contribution to the internal raw model score. It is not a clinical probability and does not establish causality.",
        "",
        "## 3. Top global features",
        "",
        "| Rank | Feature | Group | Relative SHAP contribution |",
        "|---:|---|---|---:|",
    ]
    for row in top_features.itertuples(index=False):
        lines.append(f"| {row.rank} | {row.feature} | {row.feature_group} | {row.normalized_importance:.4%} |")
    lines.extend(
        [
            "",
            "## 4. Seasonal, weather and demographic contribution",
            "",
            "| Component | Relative model importance |",
            "|---|---:|",
            f"| Seasonal/calendar | {totals['SEASONAL_TOTAL']:.4%} |",
            f"| Weather total | {totals['WEATHER_TOTAL']:.4%} |",
            f"| Demographic | {totals['DEMOGRAPHIC_TOTAL']:.4%} |",
            "",
            "The percentages are relative SHAP contributions, not percentages of disease causation.",
            "",
            "## 5. Weather windows",
            "",
            "| Window | Relative model importance |",
            "|---|---:|",
            f"| Current | {windows['CURRENT']:.4%} |",
            f"| 3 days | {windows['3D']:.4%} |",
            f"| 7 days | {windows['7D']:.4%} |",
            "",
            "## 6. Weather variable families",
            "",
            "| Weather family | Relative model importance |",
            "|---|---:|",
        ]
    )
    for row in weather_variables.itertuples(index=False):
        lines.append(f"| {row.category} | {row.relative_importance:.4%} |")
    lines.extend(["", "## 7. Disease-level patterns", "", "### Five weather-heavy diseases", "", "| Disease ID | Disease name | Weather | Top group |", "|---|---|---:|---|"])
    for row in weather_heavy.itertuples(index=False):
        lines.append(f"| {row.disease_id} | {row.disease_name} | {row.weather_importance:.4%} | {row.top_feature_group} |")
    lines.extend(["", "### Five seasonal-heavy diseases", "", "| Disease ID | Disease name | Seasonal | Top group |", "|---|---|---:|---|"])
    for row in seasonal_heavy.itertuples(index=False):
        lines.append(f"| {row.disease_id} | {row.disease_name} | {row.seasonal_importance:.4%} | {row.top_feature_group} |")
    lines.extend(
        [
            "",
            "## 8. Local Top-5 example",
            "",
            "| Rank | Disease ID | Disease name | Ranking score |",
            "|---:|---|---|---:|",
        ]
    )
    for row in local_frame.itertuples(index=False):
        lines.append(
            f"| {row.rank} | {row.disease_id} | {row.disease_name} | {row.ranking_score:.6f} |"
        )
    lines.extend(
        [
            "",
            f"Example query `{local['query_id']}` ranks disease `{local['disease_id']}` ({local['disease_name']}) at position {local['rank']} "
            f"with ranking score {local['ranking_score']:.6f}.",
            "",
            "Top positive contributors:",
            "",
        ]
    )
    for item in positive:
        lines.append(f"- {item['human_label']} (`{item['feature']}` = {item['actual_value']}): SHAP {item['shap_value']:+.6f}.")
    lines.extend(["", "Top negative contributors:", ""])
    for item in negative:
        lines.append(f"- {item['human_label']} (`{item['feature']}` = {item['actual_value']}): SHAP {item['shap_value']:+.6f}.")
    lines.extend(
        [
            "",
            "These factors push the locked model score up or down for this query; they do not diagnose disease and do not imply causes.",
            "",
            "## 9. Additivity and integrity",
            "",
            f"- SHAP additivity: **{additivity['decision']}**; maximum raw-score reconstruction error={additivity['max_absolute_error']:.12g}.",
            "- Model feature names/order, disease order, category mapping, best iterations and locked hyperparameters were verified before training.",
            "- The 221 saved boosters were reloaded from disk for reproduction and SHAP.",
            "- final_test/ and benchmark/ checksum snapshots were unchanged.",
            "- No model selection, hyperparameter tuning, TEST training or TEST-target analysis occurred.",
            "",
            "## 10. Limitations",
            "",
            "- SHAP describes this fitted model and its historical data patterns, not biological or causal mechanisms.",
            "- Correlated weather/calendar features can share or redistribute importance.",
            "- Macro-normalization gives every disease equal weight but does not measure clinical prevalence or severity.",
            "- Local explanations depend on the exact engineered query and should not be interpreted as individual medical advice.",
            f"- Total pipeline runtime: {runtime_seconds:.3f} seconds.",
            "",
        ]
    )
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    started_total = time.perf_counter()
    for directory in (MODELS_DIR, FIGURES_DIR, LOGS_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    existing_models = sorted(MODELS_DIR.glob("disease_*.txt"))
    resume_document: dict[str, Any] | None = None
    if existing_models:
        manifest_path = DEPLOY_DIR / "model_manifest.json"
        if len(existing_models) != 221 or not manifest_path.is_file():
            raise RuntimeError("Incomplete deployment model inventory; refusing to mix/rerun models")
        resume_document = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            resume_document.get("status") != "MODELS_PERSISTED_REPRODUCTION_PENDING"
            or int(resume_document.get("model_count", 0)) != 221
        ):
            raise RuntimeError("Existing model inventory is not at the safe reproduction-pending checkpoint")
    EVENT_LOG.write_text("", encoding="utf-8")
    final_snapshot_before = snapshot_tree(FINAL_DIR)
    benchmark_dir = PROJECT_ROOT / "benchmarks/lightgbm_ovr_h3_h7_h14"
    benchmark_snapshot_before = snapshot_tree(benchmark_dir)
    if not FINAL_MARKER.is_file():
        raise RuntimeError("Closed FINAL TEST marker is missing")
    final_module = load_final_module()
    locked_config = json.loads(FINAL_CONFIG.read_text(encoding="utf-8"))
    final_module.verify_locked(locked_config)
    bundle = final_module.prepare_fit_bundle(locked_config)
    if len(bundle["disease_ids"]) != 221 or len(bundle["feature_names"]) != 45:
        raise RuntimeError("Locked final disease/feature contract changed")
    stored_mapping = json.loads(FINAL_CATEGORY_MAPPINGS.read_text(encoding="utf-8"))
    if bundle["mappings"] != stored_mapping:
        raise RuntimeError("Category mapping differs from locked final mapping")
    best_frame = pd.read_csv(FINAL_BEST_ITERATIONS, dtype={"disease_group_id": str})
    best_frame = best_frame[best_frame["run_name"] == "h14_with_weather"]
    if len(best_frame) != 221 or best_frame["disease_group_id"].tolist() != bundle["disease_ids"]:
        raise RuntimeError("Locked H14 weather best iterations unavailable or reordered")
    best_iterations = {
        row.disease_group_id: int(row.best_iteration_locked)
        for row in best_frame.itertuples(index=False)
    }
    event("preflight_pass", fit_queries=len(bundle["fit_ids"]), diseases=221, features=45)

    # Persist the locked deployment contract before fitting.
    feature_map = [
        {
            "feature": feature,
            "feature_group": feature_group(feature),
            "human_label": human_label(feature),
        }
        for feature in bundle["feature_names"]
    ]
    (DEPLOY_DIR / "feature_schema.json").write_text(
        json.dumps(
            {
                "feature_count": len(bundle["feature_names"]),
                "feature_order": bundle["feature_names"],
                "features": feature_map,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (DEPLOY_DIR / "category_mappings.json").write_text(
        json.dumps(stored_mapping, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (DEPLOY_DIR / "best_iterations.json").write_text(
        json.dumps(best_iterations, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (DEPLOY_DIR / "locked_config.json").write_text(
        json.dumps(locked_config, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (DEPLOY_DIR / "README.md").write_text(
        "# Final LightGBM OVR H14 WITH WEATHER deployment\n\n"
        "221 per-disease LightGBM boosters recreated from the locked final protocol.\n"
        "Training data: TRAIN + VALIDATION only. TEST is not training data.\n"
        "This persistence run does not perform tuning or model selection.\n",
        encoding="utf-8",
    )

    fit_features = bundle["fit_features"]
    if resume_document is not None:
        manifest = list(resume_document["models"])
        training_seconds = float(resume_document["training_seconds"])
        if [str(item["disease_id"]) for item in manifest] != bundle["disease_ids"]:
            raise RuntimeError("Resume manifest disease order mismatch")
        for item in manifest:
            model_path = DEPLOY_DIR / item["model_path"]
            if not model_path.is_file() or sha256_file(model_path) != item["sha256"]:
                raise RuntimeError(f"Resume model checksum mismatch: {item['disease_id']}")
        event("resume_from_persisted_models", models=221, additional_training=False)
    else:
        target = bundle["target_matrices"][14]
        manifest = []
        training_started = time.perf_counter()
        for index, disease_id in enumerate(bundle["disease_ids"]):
            y = target[:, index]
            if np.unique(y).tolist() != [0, 1]:
                raise RuntimeError(f"Disease {disease_id}: constant H14 target")
            estimator_count = best_iterations[disease_id]
            model = LGBMClassifier(**model_params(locked_config, estimator_count))
            disease_started = time.perf_counter()
            model.fit(
                fit_features,
                y,
                categorical_feature=list(locked_config["categorical_features"]),
            )
            filename = safe_disease_filename(disease_id)
            model_path = MODELS_DIR / filename
            # LightGBM's native Windows writer cannot open this workspace's Unicode path.
            # Serialize the exact native model text, then let Python perform the UTF-8 write.
            model_text = model.booster_.model_to_string(num_iteration=estimator_count)
            model_path.write_text(model_text, encoding="utf-8")
            manifest.append(
                {
                    "index": index,
                    "disease_id": disease_id,
                    "model_path": f"models/{filename}",
                    "sha256": sha256_file(model_path),
                    "bytes": model_path.stat().st_size,
                    "n_estimators_locked": estimator_count,
                    "positive_fit_queries": int(y.sum()),
                    "training_seconds": time.perf_counter() - disease_started,
                }
            )
            del model
            if (index + 1) % 25 == 0 or index + 1 == 221:
                event("model_persist_progress", saved=index + 1, total=221)
        training_seconds = time.perf_counter() - training_started
        if len(list(MODELS_DIR.glob("disease_*.txt"))) != 221:
            raise RuntimeError("Exactly 221 model files were not persisted")
        event("all_models_persisted", models=221, training_seconds=training_seconds)
        (DEPLOY_DIR / "model_manifest.json").write_text(
            json.dumps(
                {
                    "status": "MODELS_PERSISTED_REPRODUCTION_PENDING",
                    "model": "LightGBM One-vs-Rest H14 WITH WEATHER",
                    "model_count": len(manifest),
                    "disease_order": bundle["disease_ids"],
                    "feature_order": bundle["feature_names"],
                    "training_data": "TRAIN + VALIDATION only",
                    "test_used_for_training": False,
                    "model_selection": False,
                    "hyperparameter_tuning": False,
                    "training_seconds": training_seconds,
                    "models": manifest,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    # Reproduction gate: TEST features only, no TEST target or metric.
    score_contract = json.loads(FINAL_SCORE_CONTRACT.read_text(encoding="utf-8"))
    test_ids = [str(value) for value in score_contract["query_ids"]]
    if len(test_ids) != int(score_contract["query_count"]):
        raise RuntimeError("Saved TEST score contract query count mismatch")
    test_contexts = final_module.load_selected_gzip_csv(
        final_module.CONTEXTS_PATH,
        set(test_ids),
        dtype={"query_id": str},
        require_one_context_per_id=True,
    )
    test_features = final_module.transform_features(
        test_contexts,
        test_ids,
        bundle["feature_names"],
        list(locked_config["categorical_features"]),
        stored_mapping,
    )
    old_scores = np.load(FINAL_SCORES, allow_pickle=False)
    new_scores = np.empty_like(old_scores)
    for index, item in enumerate(manifest):
        booster = load_booster(DEPLOY_DIR / item["model_path"])
        if booster.feature_name() != bundle["feature_names"]:
            raise RuntimeError(f"Saved model feature mismatch: {item['disease_id']}")
        new_scores[:, index] = booster.predict(test_features).astype(np.float32)
    difference = new_scores.astype(np.float64) - old_scores.astype(np.float64)
    old_order = np.argsort(-old_scores, axis=1, kind="stable")
    new_order = np.argsort(-new_scores, axis=1, kind="stable")
    reproduction = {
        "max_absolute_difference": float(np.max(np.abs(difference))),
        "mean_absolute_difference": float(np.mean(np.abs(difference))),
        "rmse": float(np.sqrt(np.mean(np.square(difference)))),
        "top5_agreement": float(np.mean(np.all(old_order[:, :5] == new_order[:, :5], axis=1))),
        "top10_agreement": float(np.mean(np.all(old_order[:, :10] == new_order[:, :10], axis=1))),
        "test_queries": len(test_ids),
        "test_target_loaded": False,
        "purpose": "score reproduction only; no tuning or model selection",
    }
    reproduction_pass = (
        reproduction["max_absolute_difference"] <= REPRO_MAX_ABS_TOLERANCE
        and reproduction["rmse"] <= REPRO_RMSE_TOLERANCE
        and reproduction["top5_agreement"] == 1.0
        and reproduction["top10_agreement"] == 1.0
    )
    reproduction["decision"] = "REPRODUCTION_PASS" if reproduction_pass else "REPRODUCTION_MISMATCH"
    if not reproduction_pass:
        (DEPLOY_DIR / "model_manifest.json").write_text(
            json.dumps({"models": manifest, "reproduction": reproduction}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        raise RuntimeError(f"REPRODUCTION_MISMATCH: {reproduction}")
    event("reproduction_pass", **reproduction)

    # SHAP starts only after exact reproduction passed.
    import shap

    event("shap_started", shap_version=shap.__version__, model_output="raw")
    rng = np.random.default_rng(RANDOM_SEED)
    sample_indices = np.sort(
        rng.choice(len(fit_features), size=min(SHAP_SAMPLE_SIZE, len(fit_features)), replace=False)
    )
    explanation_features = fit_features.iloc[sample_indices].reset_index(drop=True)
    raw_contexts = bundle["contexts"].set_index("query_id", drop=False).loc[bundle["fit_ids"]].reset_index(drop=True)
    explanation_raw = raw_contexts.iloc[sample_indices].reset_index(drop=True)
    feature_names = bundle["feature_names"]
    group_names = [feature_group(feature) for feature in feature_names]
    global_raw = np.zeros(len(feature_names), dtype=np.float64)
    global_normalized = np.zeros(len(feature_names), dtype=np.float64)
    global_gain_normalized = np.zeros(len(feature_names), dtype=np.float64)
    global_split_normalized = np.zeros(len(feature_names), dtype=np.float64)
    disease_rows: list[dict[str, Any]] = []
    catalog = pd.read_csv(DISEASE_CATALOG, dtype={"disease_group_id": str})
    disease_names = dict(zip(catalog["disease_group_id"], catalog["disease_group_name"]))
    additivity_errors: list[float] = []
    for index, item in enumerate(manifest):
        booster = load_booster(DEPLOY_DIR / item["model_path"])
        explainer = shap.TreeExplainer(
            booster,
            model_output="raw",
            feature_perturbation="tree_path_dependent",
        )
        shap_values, base_value = extract_shap_values(explainer, explanation_features)
        if shap_values.shape != explanation_features.shape:
            raise RuntimeError(f"Unexpected SHAP shape for disease {item['disease_id']}: {shap_values.shape}")
        raw_scores = np.asarray(booster.predict(explanation_features, raw_score=True), dtype=np.float64)
        additivity_error = float(np.max(np.abs(raw_scores - (base_value + shap_values.sum(axis=1)))))
        additivity_errors.append(additivity_error)
        mean_abs = np.mean(np.abs(shap_values), axis=0)
        normalized = normalize(mean_abs)
        gain = np.asarray(booster.feature_importance(importance_type="gain"), dtype=np.float64)
        split = np.asarray(booster.feature_importance(importance_type="split"), dtype=np.float64)
        global_raw += mean_abs
        global_normalized += normalized
        global_gain_normalized += normalize(gain)
        global_split_normalized += normalize(split)
        group_importance = {
            group: float(normalized[np.asarray(group_names) == group].sum())
            for group in sorted(set(group_names))
        }
        top_indices = np.argsort(-normalized, kind="stable")[:10]
        top_features = [
            {
                "feature": feature_names[int(feature_index)],
                "human_label": human_label(feature_names[int(feature_index)]),
                "feature_group": group_names[int(feature_index)],
                "mean_abs_shap": float(mean_abs[int(feature_index)]),
                "normalized_importance": float(normalized[int(feature_index)]),
            }
            for feature_index in top_indices
        ]
        disease_id = str(item["disease_id"])
        disease_rows.append(
            {
                "disease_id": disease_id,
                "disease_name": disease_names.get(disease_id, ""),
                "top_10_features": json.dumps(top_features, ensure_ascii=False),
                "top_feature_group": max(group_importance, key=group_importance.get),
                "weather_importance": group_importance["WEATHER_CURRENT"] + group_importance["WEATHER_3D"] + group_importance["WEATHER_7D"],
                "seasonal_importance": group_importance["SEASONAL_CALENDAR"],
                "demographic_importance": group_importance["DEMOGRAPHIC"],
                "weather_current_importance": group_importance["WEATHER_CURRENT"],
                "weather_3d_importance": group_importance["WEATHER_3D"],
                "weather_7d_importance": group_importance["WEATHER_7D"],
                "shap_additivity_max_abs_error": additivity_error,
            }
        )
        if (index + 1) % 25 == 0 or index + 1 == 221:
            event("shap_progress", diseases=index + 1, total=221)
    global_raw /= 221
    global_normalized /= 221
    global_gain_normalized /= 221
    global_split_normalized /= 221
    feature_frame = pd.DataFrame(
        {
            "feature": feature_names,
            "feature_group": group_names,
            "human_label": [human_label(feature) for feature in feature_names],
            "mean_abs_shap": global_raw,
            "normalized_importance": global_normalized,
            "macro_normalized_gain_importance": global_gain_normalized,
            "macro_normalized_split_importance": global_split_normalized,
        }
    ).sort_values("normalized_importance", ascending=False, kind="stable")
    feature_frame["rank"] = np.arange(1, len(feature_frame) + 1)
    feature_frame.to_csv(EXPLAIN_DIR / "global_shap_feature_importance.csv", index=False)

    group_frame = (
        feature_frame.groupby("feature_group", as_index=False)["normalized_importance"]
        .sum()
        .rename(columns={"normalized_importance": "relative_importance"})
        .sort_values("relative_importance", ascending=False)
    )
    group_frame["rank"] = np.arange(1, len(group_frame) + 1)
    group_frame.to_csv(EXPLAIN_DIR / "global_shap_group_importance.csv", index=False)
    group_lookup = dict(zip(group_frame["feature_group"], group_frame["relative_importance"]))
    comparison_rows = [
        {"category_type": "TOTAL", "category": "SEASONAL_TOTAL", "relative_importance": group_lookup["SEASONAL_CALENDAR"]},
        {"category_type": "TOTAL", "category": "WEATHER_TOTAL", "relative_importance": group_lookup["WEATHER_CURRENT"] + group_lookup["WEATHER_3D"] + group_lookup["WEATHER_7D"]},
        {"category_type": "TOTAL", "category": "DEMOGRAPHIC_TOTAL", "relative_importance": group_lookup["DEMOGRAPHIC"]},
        {"category_type": "WEATHER_WINDOW", "category": "CURRENT", "relative_importance": group_lookup["WEATHER_CURRENT"]},
        {"category_type": "WEATHER_WINDOW", "category": "3D", "relative_importance": group_lookup["WEATHER_3D"]},
        {"category_type": "WEATHER_WINDOW", "category": "7D", "relative_importance": group_lookup["WEATHER_7D"]},
    ]
    for variable in ("TEMPERATURE", "HUMIDITY", "RAIN_PRECIPITATION", "WIND", "WEATHER_CODE", "OTHER_WEATHER"):
        weather_mask = feature_frame["feature_group"].str.startswith("WEATHER_")
        importance = float(
            feature_frame.loc[
                weather_mask & (feature_frame["feature"].map(weather_variable) == variable),
                "normalized_importance",
            ].sum()
        )
        if importance > 0:
            comparison_rows.append(
                {"category_type": "WEATHER_VARIABLE", "category": variable, "relative_importance": importance}
            )
    comparison_frame = pd.DataFrame(comparison_rows)
    comparison_frame.to_csv(EXPLAIN_DIR / "weather_vs_seasonal.csv", index=False)
    disease_frame = pd.DataFrame(disease_rows)
    disease_frame.to_csv(EXPLAIN_DIR / "disease_shap_summary.csv", index=False)

    # An actual feature-only selected query: rainy-season August male child with maximum 7d rain.
    candidate = raw_contexts[
        raw_contexts["age_group"].eq("1-5 tuổi")
        & raw_contexts["gender"].eq("Nam")
        & raw_contexts["month"].eq(8)
        & raw_contexts["season"].eq("Mùa mưa")
    ]
    local_raw = (
        candidate.sort_values("rain_sum_7d", ascending=False).iloc[0]
        if len(candidate)
        else explanation_raw.iloc[0]
    )
    local_features = final_module.transform_features(
        pd.DataFrame([local_raw]),
        [str(local_raw["query_id"])],
        feature_names,
        list(locked_config["categorical_features"]),
        stored_mapping,
    )
    local_rows = explain_query(local_features, local_raw, manifest, disease_names, top_k=5)
    local_frame = pd.DataFrame(local_rows)
    local_frame.to_csv(EXPLAIN_DIR / "local_explanation_examples.csv", index=False)

    additivity = {
        "max_absolute_error": float(max(additivity_errors)),
        "mean_max_error_across_diseases": float(np.mean(additivity_errors)),
    }
    additivity["decision"] = (
        "PASS" if additivity["max_absolute_error"] <= SHAP_ADDITIVITY_TOLERANCE else "FAIL"
    )
    if additivity["decision"] != "PASS":
        raise RuntimeError(f"SHAP additivity failed: {additivity}")
    create_figures(feature_frame, group_frame, comparison_frame, local_frame)

    final_snapshot_after = snapshot_tree(FINAL_DIR)
    benchmark_snapshot_after = snapshot_tree(benchmark_dir)
    if final_snapshot_before != final_snapshot_after:
        raise RuntimeError("final_test/ changed during persistence/explainability")
    if benchmark_snapshot_before != benchmark_snapshot_after:
        raise RuntimeError("benchmark/ changed during persistence/explainability")
    current_process_seconds = time.perf_counter() - started_total
    runtime_seconds = current_process_seconds + (training_seconds if resume_document is not None else 0.0)
    manifest_document = {
        "status": "DEPLOYMENT_READY_REPRODUCTION_PASS",
        "model": "LightGBM One-vs-Rest H14 WITH WEATHER",
        "model_count": len(manifest),
        "disease_order": bundle["disease_ids"],
        "feature_order": feature_names,
        "training_data": "TRAIN + VALIDATION only",
        "test_used_for_training": False,
        "model_selection": False,
        "hyperparameter_tuning": False,
        "training_seconds": training_seconds,
        "total_successful_runtime_seconds": runtime_seconds,
        "models": manifest,
        "reproduction": reproduction,
        "shap": {
            "version": shap.__version__,
            "sample_size": len(explanation_features),
            "random_seed": RANDOM_SEED,
            "model_output": "raw",
            "additivity": additivity,
        },
    }
    (DEPLOY_DIR / "model_manifest.json").write_text(
        json.dumps(manifest_document, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_report(
        feature_frame,
        group_frame,
        comparison_frame,
        disease_frame,
        local_frame,
        reproduction,
        additivity,
        runtime_seconds,
    )
    (EXPLAIN_DIR / "explain_config.json").write_text(
        json.dumps(
            {
                "locked_model": "LightGBM One-vs-Rest H14 WITH WEATHER",
                "model_count": 221,
                "shap_sample_size": len(explanation_features),
                "random_seed": RANDOM_SEED,
                "model_output": "raw",
                "reproduction_thresholds": {
                    "max_absolute_difference": REPRO_MAX_ABS_TOLERANCE,
                    "rmse": REPRO_RMSE_TOLERANCE,
                    "ordered_top_k_agreement": 1.0,
                },
                "shap_additivity_tolerance": SHAP_ADDITIVITY_TOLERANCE,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    event(
        "explainability_complete",
        reproduction=reproduction["decision"],
        shap_additivity=additivity["decision"],
        runtime_seconds=runtime_seconds,
    )
    print(
        json.dumps(
            {
                "models_saved": len(manifest),
                "reproduction": reproduction,
                "shap_additivity": additivity,
                "runtime_seconds": runtime_seconds,
                "report": str(REPORT_PATH),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        (LOGS_DIR / "failure.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise
