import json
import math
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from sklearn.tree import DecisionTreeRegressor


BASE_DIR = Path(__file__).resolve().parent
TRAIN_5_DIR = BASE_DIR.parent
SOURCE_MONTHLY_CSV = TRAIN_5_DIR / "results" / "train_monthly_statistics.csv"

OUTPUT_MODEL_DIR = BASE_DIR / "models"
OUTPUT_RESULT_DIR = BASE_DIR / "results"

OUTPUT_MODEL_DIR.mkdir(exist_ok=True)
OUTPUT_RESULT_DIR.mkdir(exist_ok=True)


FEATURE_COLS = [
    "disease_target",
    "age_group",
    "target_season",
    "target_year",
    "target_month_num",
    "target_month_sin",
    "target_month_cos",
    "lag_1",
    "lag_2",
    "lag_3",
    "lag_4",
    "lag_5",
    "rolling_3",
    "rolling_5",
    "change_1",
]

CATEGORICAL_FEATURES = ["disease_target", "age_group", "target_season"]
NUMERIC_FEATURES = [
    "target_year",
    "target_month_num",
    "target_month_sin",
    "target_month_cos",
    "lag_1",
    "lag_2",
    "lag_3",
    "lag_4",
    "lag_5",
    "rolling_3",
    "rolling_5",
    "change_1",
]
TARGET_COL = "target_cases"


def month_to_season_vn(month):
    if month in [12, 1, 2, 3, 4]:
        return "Mùa khô"
    if month in [5, 6, 7, 8, 9, 10, 11]:
        return "Mùa mưa"
    return "Không rõ"


def load_monthly_data():
    if not SOURCE_MONTHLY_CSV.exists():
        raise FileNotFoundError(f"Không tìm thấy file dữ liệu: {SOURCE_MONTHLY_CSV}")

    monthly = pd.read_csv(SOURCE_MONTHLY_CSV, encoding="utf-8-sig")

    required_cols = {
        "disease_target",
        "age_group",
        "period",
        "year",
        "month_num",
        "season",
        "case_count",
    }
    missing = sorted(required_cols - set(monthly.columns))
    if missing:
        raise ValueError(f"File monthly statistics thiếu cột: {missing}")

    monthly["period"] = monthly["period"].astype(str)
    monthly["year"] = monthly["year"].astype(int)
    monthly["month_num"] = monthly["month_num"].astype(int)
    monthly["case_count"] = monthly["case_count"].fillna(0).astype(int)

    return monthly


def create_training_dataset(monthly_full):
    data = monthly_full.copy()
    data["period_dt"] = pd.PeriodIndex(data["period"], freq="M").to_timestamp()
    data = data.sort_values(["disease_target", "age_group", "period_dt"]).reset_index(drop=True)

    group_cols = ["disease_target", "age_group"]

    for lag in range(1, 6):
        data[f"lag_{lag}"] = data.groupby(group_cols)["case_count"].shift(lag)

    data["rolling_3"] = data.groupby(group_cols)["case_count"].transform(
        lambda s: s.shift(1).rolling(window=3, min_periods=1).mean()
    )
    data["rolling_5"] = data.groupby(group_cols)["case_count"].transform(
        lambda s: s.shift(1).rolling(window=5, min_periods=1).mean()
    )
    data["change_1"] = data["lag_1"] - data["lag_2"]

    data["target_year"] = data["year"]
    data["target_month_num"] = data["month_num"]
    data["target_season"] = data["season"].fillna(data["month_num"].apply(month_to_season_vn))
    data["target_month_sin"] = np.sin(2 * np.pi * data["target_month_num"] / 12)
    data["target_month_cos"] = np.cos(2 * np.pi * data["target_month_num"] / 12)
    data["target_cases"] = data["case_count"]

    train_data = data.dropna(subset=["lag_1"]).copy()

    fill_cols = ["lag_2", "lag_3", "lag_4", "lag_5", "rolling_3", "rolling_5", "change_1"]
    for col in fill_cols:
        train_data[col] = train_data[col].fillna(0)

    return train_data


def make_preprocessor():
    return ColumnTransformer(
        transformers=[
            ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES),
            ("num", "passthrough", NUMERIC_FEATURES),
        ]
    )


def make_models():
    return {
        "Decision Tree": Pipeline(
            steps=[
                ("preprocess", make_preprocessor()),
                (
                    "model",
                    DecisionTreeRegressor(
                        random_state=42,
                        min_samples_leaf=2,
                    ),
                ),
            ]
        ),
        "Random Forest": Pipeline(
            steps=[
                ("preprocess", make_preprocessor()),
                (
                    "model",
                    RandomForestRegressor(
                        n_estimators=300,
                        random_state=42,
                        min_samples_leaf=2,
                        n_jobs=-1,
                    ),
                ),
            ]
        ),
    }


def evaluate(y_true, y_pred):
    y_pred = np.clip(np.asarray(y_pred, dtype=float), 0, None)
    return {
        "MAE": mean_absolute_error(y_true, y_pred),
        "RMSE": math.sqrt(mean_squared_error(y_true, y_pred)),
        "R2": r2_score(y_true, y_pred) if len(y_true) > 1 else np.nan,
    }


def get_feature_importance(pipeline):
    preprocessor = pipeline.named_steps["preprocess"]
    model = pipeline.named_steps["model"]

    feature_names = preprocessor.get_feature_names_out()
    importance = getattr(model, "feature_importances_", None)
    if importance is None:
        return pd.DataFrame(columns=["feature", "importance"])

    df = pd.DataFrame({"feature": feature_names, "importance": importance})
    return df.sort_values("importance", ascending=False).reset_index(drop=True)


def write_markdown_report(summary, metrics_df, importance_files):
    rf = metrics_df[metrics_df["model"] == "Random Forest"].iloc[0]
    dt = metrics_df[metrics_df["model"] == "Decision Tree"].iloc[0]

    mae_improve = ((dt["MAE"] - rf["MAE"]) / dt["MAE"]) * 100 if dt["MAE"] else 0
    rmse_improve = ((dt["RMSE"] - rf["RMSE"]) / dt["RMSE"]) * 100 if dt["RMSE"] else 0

    lines = [
        "# So sánh Decision Tree và Random Forest",
        "",
        "## Dữ liệu",
        f"- Nguồn đọc: `{SOURCE_MONTHLY_CSV}`",
        f"- Số dòng dữ liệu tháng ban đầu: {summary['monthly_rows']}",
        f"- Số dòng dùng để train/evaluate sau khi tạo lag: {summary['model_rows']}",
        f"- Khoảng thời gian dữ liệu: {summary['period_min']} đến {summary['period_max']}",
        f"- Tập train: {summary['train_period_start']} đến {summary['train_period_end']} ({summary['train_period_count']} tháng)",
        f"- Tập test: {summary['test_period_start']} đến {summary['test_period_end']} ({summary['test_period_count']} tháng)",
        "",
        "## Kết quả so sánh",
        "| Model | MAE | RMSE | R2 | Thời gian train eval (giây) |",
        "|---|---:|---:|---:|---:|",
    ]

    for _, row in metrics_df.iterrows():
        lines.append(
            f"| {row['model']} | {row['MAE']:.4f} | {row['RMSE']:.4f} | "
            f"{row['R2']:.6f} | {row['train_time_seconds']:.4f} |"
        )

    lines.extend(
        [
            "",
            "## Kết luận",
            (
                f"Random Forest có MAE thấp hơn Decision Tree khoảng {mae_improve:.2f}% "
                f"và RMSE thấp hơn khoảng {rmse_improve:.2f}% trên tập test theo thời gian."
            ),
            (
                "Điều này cho thấy Random Forest dự đoán ổn định hơn vì dùng nhiều cây quyết định "
                "và lấy trung bình kết quả, nhờ đó giảm overfit so với một Decision Tree đơn."
            ),
            "",
            "## File đã tạo",
            "- `models/decision_tree_model.pkl`",
            "- `models/random_forest_model.pkl`",
            "- `results/model_comparison_metrics.csv`",
            "- `results/test_predictions.csv`",
        ]
    )

    for label, filename in importance_files.items():
        lines.append(f"- `results/{filename}`: feature importance của {label}")

    (BASE_DIR / "bao_cao_so_sanh_model.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    start_all = time.time()

    monthly = load_monthly_data()
    train_data = create_training_dataset(monthly)

    periods = sorted(train_data["period"].unique())
    split_idx = max(1, int(len(periods) * 0.8))
    train_periods = periods[:split_idx]
    test_periods = periods[split_idx:]

    df_train = train_data[train_data["period"].isin(train_periods)].copy()
    df_test = train_data[train_data["period"].isin(test_periods)].copy()

    X_train = df_train[FEATURE_COLS]
    y_train = df_train[TARGET_COL]
    X_test = df_test[FEATURE_COLS]
    y_test = df_test[TARGET_COL]

    metrics = []
    prediction_df = df_test[
        ["period", "disease_target", "age_group", "target_cases", "lag_1", "rolling_3", "rolling_5"]
    ].copy()
    prediction_df = prediction_df.rename(columns={"target_cases": "actual_cases"})

    eval_models = make_models()

    for model_name, pipeline in eval_models.items():
        start = time.time()
        pipeline.fit(X_train, y_train)
        train_time = time.time() - start

        pred = np.clip(pipeline.predict(X_test), 0, None)
        rounded_pred = np.round(pred).astype(int)

        model_metrics = evaluate(y_test, pred)
        metrics.append(
            {
                "model": model_name,
                "train_rows": len(df_train),
                "test_rows": len(df_test),
                "train_time_seconds": train_time,
                **model_metrics,
            }
        )

        safe_name = "decision_tree" if model_name == "Decision Tree" else "random_forest"
        prediction_df[f"{safe_name}_predicted_cases"] = rounded_pred
        prediction_df[f"{safe_name}_abs_error"] = (prediction_df["actual_cases"] - rounded_pred).abs()

        importance_df = get_feature_importance(pipeline)
        importance_df.to_csv(
            OUTPUT_RESULT_DIR / f"{safe_name}_feature_importance.csv",
            index=False,
            encoding="utf-8-sig",
        )

    metrics_df = pd.DataFrame(metrics).sort_values(["MAE", "RMSE"]).reset_index(drop=True)
    metrics_df_rounded = metrics_df.copy()
    for col in ["train_time_seconds", "MAE", "RMSE", "R2"]:
        metrics_df_rounded[col] = metrics_df_rounded[col].round(6)

    metrics_df_rounded.to_csv(
        OUTPUT_RESULT_DIR / "model_comparison_metrics.csv",
        index=False,
        encoding="utf-8-sig",
    )
    prediction_df.to_csv(
        OUTPUT_RESULT_DIR / "test_predictions.csv",
        index=False,
        encoding="utf-8-sig",
    )

    final_models = make_models()
    X_all = train_data[FEATURE_COLS]
    y_all = train_data[TARGET_COL]

    final_models["Decision Tree"].fit(X_all, y_all)
    final_models["Random Forest"].fit(X_all, y_all)

    joblib.dump(final_models["Decision Tree"], OUTPUT_MODEL_DIR / "decision_tree_model.pkl")
    joblib.dump(final_models["Random Forest"], OUTPUT_MODEL_DIR / "random_forest_model.pkl")

    summary = {
        "monthly_rows": int(len(monthly)),
        "model_rows": int(len(train_data)),
        "period_min": train_data["period"].min(),
        "period_max": train_data["period"].max(),
        "period_count": int(len(periods)),
        "train_period_start": train_periods[0],
        "train_period_end": train_periods[-1],
        "train_period_count": int(len(train_periods)),
        "test_period_start": test_periods[0],
        "test_period_end": test_periods[-1],
        "test_period_count": int(len(test_periods)),
        "train_rows": int(len(df_train)),
        "test_rows": int(len(df_test)),
        "total_runtime_seconds": round(time.time() - start_all, 2),
    }

    (OUTPUT_RESULT_DIR / "experiment_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    write_markdown_report(
        summary=summary,
        metrics_df=metrics_df,
        importance_files={
            "Decision Tree": "decision_tree_feature_importance.csv",
            "Random Forest": "random_forest_feature_importance.csv",
        },
    )

    print("Hoàn tất so sánh Decision Tree và Random Forest.")
    print(metrics_df_rounded.to_string(index=False))
    print(f"Đã lưu model tại: {OUTPUT_MODEL_DIR}")
    print(f"Đã lưu kết quả tại: {OUTPUT_RESULT_DIR}")


if __name__ == "__main__":
    main()
