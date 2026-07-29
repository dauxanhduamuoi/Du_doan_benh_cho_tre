import json
import math
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.neighbors import KNeighborsRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.tree import DecisionTreeRegressor


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = Path(__file__).resolve().parent

TRAIN_DATA_PATH = ROOT / "train_history.xlsx"
PATIENT_SHEET = "DS-BenhNhan"
DISEASE_SHEET = "DS-MaBenh"

ICD_ADMISSION_COL = "icdNV"
ICD_DISCHARGE_COL = "icdxuatvien"
CHECK_IN_DATE_COL = "check_in_date"
DATE_OF_BIRTH_COL = "date_of_birth"
GENDER_COL = "gender"

ICD_CODE_COL = "MAICD"
DISEASE_NAME_COL = "TENICD"
DISEASE_GROUP_COL = "TENNHOMICD"

PREDICT_LEVEL = "group"


def parse_excel_date_value(x):
    if pd.isna(x):
        return pd.NaT
    if isinstance(x, pd.Timestamp):
        return pd.to_datetime(x)
    try:
        num = float(x)
        if 20000 <= num <= 80000:
            return pd.to_datetime("1899-12-30") + pd.to_timedelta(num, unit="D")
    except Exception:
        pass
    return pd.to_datetime(x, errors="coerce", dayfirst=True)


def parse_mixed_excel_date(series):
    return series.apply(parse_excel_date_value)


def normalize_icd(x):
    if pd.isna(x):
        return np.nan
    return str(x).strip().upper()


def calculate_age_months(check_in_date, date_of_birth):
    if pd.isna(check_in_date) or pd.isna(date_of_birth):
        return np.nan
    if check_in_date < date_of_birth:
        return np.nan
    age_months = (
        (check_in_date.year - date_of_birth.year) * 12
        + (check_in_date.month - date_of_birth.month)
        - (1 if check_in_date.day < date_of_birth.day else 0)
    )
    if age_months < 0:
        return np.nan
    return age_months


def to_age_group(age_months):
    if pd.isna(age_months):
        return "Không rõ"
    if age_months < 12:
        return "Dưới 1 tuổi"
    if age_months <= 60:
        return "1-5 tuổi"
    if age_months <= 120:
        return "6-10 tuổi"
    if age_months <= 180:
        return "11-15 tuổi"
    return "Trên 15 tuổi"


def month_to_season_vn(month):
    if month in [12, 1, 2, 3, 4]:
        return "Mùa khô"
    if month in [5, 6, 7, 8, 9, 10, 11]:
        return "Mùa mưa"
    return "Không rõ"


def load_disease_codes_from_excel(file_path):
    disease_codes = pd.read_excel(file_path, sheet_name=DISEASE_SHEET)
    disease_codes[ICD_CODE_COL] = disease_codes[ICD_CODE_COL].apply(normalize_icd)
    return disease_codes


def load_patients_from_excel(file_path, disease_codes):
    patients = pd.read_excel(file_path, sheet_name=PATIENT_SHEET)

    patients[CHECK_IN_DATE_COL] = parse_mixed_excel_date(patients[CHECK_IN_DATE_COL])
    patients[DATE_OF_BIRTH_COL] = parse_mixed_excel_date(patients[DATE_OF_BIRTH_COL])
    patients[ICD_ADMISSION_COL] = patients[ICD_ADMISSION_COL].apply(normalize_icd)
    patients[ICD_DISCHARGE_COL] = patients[ICD_DISCHARGE_COL].apply(normalize_icd)

    patients["main_icd"] = patients[ICD_DISCHARGE_COL].fillna(patients[ICD_ADMISSION_COL])
    patients["main_icd"] = patients["main_icd"].apply(normalize_icd)

    df = patients.merge(
        disease_codes,
        left_on="main_icd",
        right_on=ICD_CODE_COL,
        how="left",
    )

    df["age_months"] = df.apply(
        lambda row: calculate_age_months(row[CHECK_IN_DATE_COL], row[DATE_OF_BIRTH_COL]),
        axis=1,
    )
    df["age"] = df["age_months"] / 12.0
    df["age_group"] = df["age_months"].apply(to_age_group)
    df["year"] = df[CHECK_IN_DATE_COL].dt.year
    df["month_num"] = df[CHECK_IN_DATE_COL].dt.month
    df["period"] = df[CHECK_IN_DATE_COL].dt.to_period("M").astype(str)
    df["season"] = df["month_num"].apply(month_to_season_vn)

    df["disease_name"] = df[DISEASE_NAME_COL].fillna("Không rõ bệnh")
    df["disease_group"] = df[DISEASE_GROUP_COL].fillna("Không rõ nhóm bệnh")
    df[GENDER_COL] = df[GENDER_COL].fillna("Không rõ").astype(str).str.strip()

    return df.dropna(subset=[CHECK_IN_DATE_COL, "main_icd"])


def create_monthly_stats(df):
    target_col = "disease_group" if PREDICT_LEVEL == "group" else "disease_name"
    monthly_stats = (
        df.groupby(["period", "year", "month_num", "season", target_col, "age_group"])
        .size()
        .reset_index(name="case_count")
    )
    return monthly_stats.rename(columns={target_col: "disease_target"})


def complete_monthly_grid(monthly_stats, all_combinations=None, start_period=None, end_period=None):
    if monthly_stats.empty:
        return monthly_stats

    min_period = pd.Period(start_period or monthly_stats["period"].min(), freq="M")
    max_period = pd.Period(end_period or monthly_stats["period"].max(), freq="M")
    all_periods = pd.period_range(min_period, max_period, freq="M").astype(str)

    period_df = pd.DataFrame({"period": all_periods})
    period_index = pd.PeriodIndex(period_df["period"], freq="M")
    period_df["year"] = period_index.year
    period_df["month_num"] = period_index.month
    period_df["season"] = period_df["month_num"].apply(month_to_season_vn)

    combinations = (
        monthly_stats[["disease_target", "age_group"]].drop_duplicates()
        if all_combinations is None
        else all_combinations.copy()
    )
    grid = combinations.merge(period_df, how="cross")
    full = grid.merge(
        monthly_stats[["period", "disease_target", "age_group", "case_count"]],
        on=["period", "disease_target", "age_group"],
        how="left",
    )
    full["case_count"] = full["case_count"].fillna(0).astype(int)
    return full.sort_values(["disease_target", "age_group", "period"]).reset_index(drop=True)


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
    data["target_season"] = data["season"]
    data["target_month_sin"] = np.sin(2 * np.pi * data["target_month_num"] / 12)
    data["target_month_cos"] = np.cos(2 * np.pi * data["target_month_num"] / 12)
    data["target_cases"] = data["case_count"]

    train_data = data.dropna(subset=["lag_1"]).copy()
    fill_cols = ["lag_2", "lag_3", "lag_4", "lag_5", "rolling_3", "rolling_5", "change_1"]
    for col in fill_cols:
        train_data[col] = train_data[col].fillna(0)
    return data, train_data


def regression_metrics(y_true, y_pred):
    y_pred = np.clip(np.asarray(y_pred, dtype=float), 0, None)
    return {
        "MAE": mean_absolute_error(y_true, y_pred),
        "RMSE": math.sqrt(mean_squared_error(y_true, y_pred)),
        "R2": r2_score(y_true, y_pred) if len(y_true) > 1 else np.nan,
    }


def build_preprocessor(scale_numeric=False):
    numeric_transformer = StandardScaler() if scale_numeric else "passthrough"
    return ColumnTransformer(
        transformers=[
            ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CATEGORICAL_FEATURES),
            ("num", numeric_transformer, NUMERIC_FEATURES),
        ],
        sparse_threshold=0.0,
    )


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


def main():
    start_all = time.time()
    disease_codes = load_disease_codes_from_excel(TRAIN_DATA_PATH)
    train_df = load_patients_from_excel(TRAIN_DATA_PATH, disease_codes)
    train_monthly = create_monthly_stats(train_df)
    train_monthly_full = complete_monthly_grid(train_monthly)
    _, train_data = create_training_dataset(train_monthly_full)

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

    rows = []

    baseline_predictions = {
        "Baseline tháng trước (lag_1)": df_test["lag_1"].to_numpy(),
        "Baseline TB 3 tháng": df_test["rolling_3"].to_numpy(),
        "Baseline TB 5 tháng": df_test["rolling_5"].to_numpy(),
    }
    for name, pred in baseline_predictions.items():
        rows.append({"model": name, "train_time_seconds": 0.0, **regression_metrics(y_test, pred)})

    models = [
        (
            "Dummy trung bình train",
            Pipeline(
                [
                    ("preprocess", build_preprocessor()),
                    ("model", DummyRegressor(strategy="mean")),
                ]
            ),
        ),
        (
            "Ridge tuyến tính",
            Pipeline(
                [
                    ("preprocess", build_preprocessor(scale_numeric=True)),
                    ("model", Ridge(alpha=1.0)),
                ]
            ),
        ),
        (
            "KNN k=5",
            Pipeline(
                [
                    ("preprocess", build_preprocessor(scale_numeric=True)),
                    ("model", KNeighborsRegressor(n_neighbors=5, weights="distance")),
                ]
            ),
        ),
        (
            "Decision Tree đơn",
            Pipeline(
                [
                    ("preprocess", build_preprocessor()),
                    ("model", DecisionTreeRegressor(random_state=42, min_samples_leaf=2)),
                ]
            ),
        ),
        (
            "Gradient Boosting",
            Pipeline(
                [
                    ("preprocess", build_preprocessor()),
                    ("model", GradientBoostingRegressor(random_state=42)),
                ]
            ),
        ),
        (
            "Random Forest 300 cây",
            Pipeline(
                [
                    ("preprocess", build_preprocessor()),
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
        ),
    ]

    fitted_models = {}
    predictions = {}
    for name, pipe in models:
        start = time.time()
        pipe.fit(X_train, y_train)
        train_time = time.time() - start
        pred = pipe.predict(X_test)
        fitted_models[name] = pipe
        predictions[name] = np.clip(pred, 0, None)
        rows.append({"model": name, "train_time_seconds": train_time, **regression_metrics(y_test, pred)})

    metrics_df = pd.DataFrame(rows).sort_values(["MAE", "RMSE"]).reset_index(drop=True)
    metrics_df["MAE"] = metrics_df["MAE"].round(4)
    metrics_df["RMSE"] = metrics_df["RMSE"].round(4)
    metrics_df["R2"] = metrics_df["R2"].round(6)
    metrics_df["train_time_seconds"] = metrics_df["train_time_seconds"].round(4)
    metrics_df.to_csv(OUT_DIR / "model_comparison_metrics.csv", index=False, encoding="utf-8-sig")

    rf_model = fitted_models["Random Forest 300 cây"]
    joblib.dump(rf_model, OUT_DIR / "random_forest_comparison_model.pkl")

    rf_pred = np.round(predictions["Random Forest 300 cây"]).astype(int)
    test_result = df_test[
        ["period", "disease_target", "age_group", "target_cases", "lag_1", "rolling_3", "rolling_5"]
    ].copy()
    test_result["rf_predicted_cases"] = rf_pred
    test_result["rf_abs_error"] = (test_result["target_cases"] - test_result["rf_predicted_cases"]).abs()
    test_result.sort_values("rf_abs_error", ascending=False).to_csv(
        OUT_DIR / "random_forest_test_predictions.csv",
        index=False,
        encoding="utf-8-sig",
    )

    top_group_eval = []
    for disease, temp in test_result.groupby("disease_target"):
        if len(temp) < 5:
            continue
        top_group_eval.append(
            {
                "disease_target": disease,
                "rows": len(temp),
                "total_actual_cases": int(temp["target_cases"].sum()),
                "MAE": mean_absolute_error(temp["target_cases"], temp["rf_predicted_cases"]),
                "RMSE": math.sqrt(mean_squared_error(temp["target_cases"], temp["rf_predicted_cases"])),
                "R2": r2_score(temp["target_cases"], temp["rf_predicted_cases"])
                if len(temp) > 1
                else np.nan,
            }
        )
    group_eval_df = pd.DataFrame(top_group_eval).sort_values("total_actual_cases", ascending=False)
    group_eval_df[["MAE", "RMSE", "R2"]] = group_eval_df[["MAE", "RMSE", "R2"]].round(4)
    group_eval_df.to_csv(OUT_DIR / "random_forest_group_evaluation.csv", index=False, encoding="utf-8-sig")

    preprocessor = rf_model.named_steps["preprocess"]
    rf = rf_model.named_steps["model"]
    feature_names = list(preprocessor.get_feature_names_out())
    importance_df = pd.DataFrame(
        {
            "feature": feature_names,
            "importance": rf.feature_importances_,
        }
    ).sort_values("importance", ascending=False)
    importance_df["importance"] = importance_df["importance"].round(6)
    importance_df.to_csv(OUT_DIR / "random_forest_feature_importance.csv", index=False, encoding="utf-8-sig")

    rf_row = metrics_df.loc[metrics_df["model"] == "Random Forest 300 cây"].iloc[0].to_dict()
    lag_row = metrics_df.loc[metrics_df["model"] == "Baseline tháng trước (lag_1)"].iloc[0].to_dict()
    best_row = metrics_df.iloc[0].to_dict()
    summary = {
        "source_file": str(TRAIN_DATA_PATH),
        "patient_rows_after_cleaning": int(len(train_df)),
        "monthly_rows": int(len(train_monthly_full)),
        "model_rows": int(len(train_data)),
        "period_min": train_data["period"].min(),
        "period_max": train_data["period"].max(),
        "period_count": int(len(periods)),
        "train_periods": train_periods,
        "test_periods": test_periods,
        "train_rows": int(len(df_train)),
        "test_rows": int(len(df_test)),
        "disease_age_combinations": int(train_monthly_full[["disease_target", "age_group"]].drop_duplicates().shape[0]),
        "best_model_by_mae": best_row,
        "random_forest": rf_row,
        "baseline_lag_1": lag_row,
        "rf_mae_improvement_vs_lag_1_percent": round(
            (lag_row["MAE"] - rf_row["MAE"]) / lag_row["MAE"] * 100, 2
        )
        if lag_row["MAE"] != 0
        else None,
        "total_runtime_seconds": round(time.time() - start_all, 2),
    }
    (OUT_DIR / "experiment_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    report = [
        "# Random Forest justification experiment",
        "",
        "## Data and split",
        f"- Source: `{TRAIN_DATA_PATH.name}`",
        f"- Patient rows after cleaning: {summary['patient_rows_after_cleaning']}",
        f"- Training rows after monthly lag features: {summary['model_rows']}",
        f"- Period range: {summary['period_min']} to {summary['period_max']} ({summary['period_count']} monthly periods)",
        f"- Train periods: {train_periods[0]} to {train_periods[-1]} ({len(train_periods)} periods)",
        f"- Test periods: {test_periods[0]} to {test_periods[-1]} ({len(test_periods)} periods)",
        "",
        "## Model comparison",
        metrics_df.to_markdown(index=False),
        "",
        "## Main conclusion",
        (
            f"Random Forest reduces MAE by {summary['rf_mae_improvement_vs_lag_1_percent']}% "
            "compared with the previous-month baseline."
        ),
        "",
        "## Top Random Forest feature importances",
        importance_df.head(15).to_markdown(index=False),
        "",
        "Generated files stay inside this experiment folder.",
    ]
    (OUT_DIR / "random_forest_justification_report.md").write_text("\n".join(report), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("\nSaved outputs to:", OUT_DIR)


if __name__ == "__main__":
    main()
