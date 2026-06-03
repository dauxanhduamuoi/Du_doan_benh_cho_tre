"""
Train model AI thời tiết và lưu vào app/ml/weather_ai_risk_model.joblib.

Chạy từ thư mục backend:
    python scripts/train_weather_ai_model.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import joblib
import numpy as np
import pandas as pd

from scripts.build_weather_ai_dataset import (
    OUTPUT_COLUMNS,
    WEATHER_FEATURE_COLS,
    build_daily_weather,
    build_disease_codes,
    create_negative_samples,
    load_patient_cases,
)

CATEGORICAL_FEATURES = [
    "age_group",
    "gender",
    "disease_group_id",
    "report_group_code",
    "season",
    "weather_code",
]
NUMERIC_FEATURES = ["month", *[c for c in WEATHER_FEATURE_COLS if c != "weather_code"]]
FEATURE_COLUMNS = CATEGORICAL_FEATURES + NUMERIC_FEATURES


def build_dataset_in_memory(weather_csv: Path, train_history: Path, negative_ratio: int, random_seed: int):
    weather = build_daily_weather(weather_csv)
    disease_codes = build_disease_codes(train_history)
    positive, stats = load_patient_cases(train_history, disease_codes)

    before = len(positive)
    positive = positive.merge(weather[["date"]], on="date", how="inner")
    stats["dropped_positive_rows_outside_weather_range"] = int(before - len(positive))
    if positive.empty:
        raise ValueError("Không có dòng bệnh nào khớp ngày với weather.")

    negative = create_negative_samples(positive, weather, negative_ratio, random_seed)
    dataset = pd.concat([positive, negative], ignore_index=True)
    dataset = dataset.merge(weather, on="date", how="left")
    if dataset[WEATHER_FEATURE_COLS].isna().any().any():
        missing = int(dataset[WEATHER_FEATURE_COLS].isna().any(axis=1).sum())
        raise ValueError(f"Có {missing} dòng thiếu weather.")

    dataset = dataset.sample(frac=1, random_state=random_seed).reset_index(drop=True)
    dataset["date"] = dataset["date"].dt.strftime("%Y-%m-%d")
    dataset = dataset[OUTPUT_COLUMNS]
    return dataset, weather, stats


def train(weather_csv: Path, train_history: Path, output_model: Path, negative_ratio: int, random_seed: int):
    print("[1/4] Build dataset...", flush=True)
    dataset, weather, stats = build_dataset_in_memory(weather_csv, train_history, negative_ratio, random_seed)
    print(f"  rows={len(dataset):,}, cases={int(dataset['case_count'].sum()):,}", flush=True)

    # Import sklearn sau khi build dataset để tránh lỗi môi trường/đọc Excel không cần thiết.
    import sklearn
    from sklearn.compose import ColumnTransformer
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import Ridge, SGDClassifier
    from sklearn.metrics import mean_absolute_error, roc_auc_score
    from sklearn.model_selection import train_test_split
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler

    for col in CATEGORICAL_FEATURES:
        dataset[col] = dataset[col].astype(str)

    X = dataset[FEATURE_COLUMNS].copy()
    y_cls = dataset["has_case"].astype(int)
    y_reg = np.log1p(dataset["case_count"].astype(float))

    X_train, X_test, y_cls_train, y_cls_test, y_reg_train, y_reg_test = train_test_split(
        X, y_cls, y_reg, test_size=0.2, random_state=random_seed, stratify=y_cls
    )

    def build_preprocessor():
        categorical_pipe = Pipeline([
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("encoder", OneHotEncoder(handle_unknown="ignore", sparse_output=True)),
        ])
        numeric_pipe = Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler(with_mean=False)),
        ])
        return ColumnTransformer([
            ("cat", categorical_pipe, CATEGORICAL_FEATURES),
            ("num", numeric_pipe, NUMERIC_FEATURES),
        ], sparse_threshold=0.3)

    classifier = Pipeline([
        ("preprocess", build_preprocessor()),
        ("model", SGDClassifier(
            loss="log_loss",
            alpha=0.0001,
            max_iter=20,
            tol=1e-3,
            class_weight="balanced",
            random_state=random_seed,
        )),
    ])
    regressor = Pipeline([
        ("preprocess", build_preprocessor()),
        ("model", Ridge(alpha=1.0, random_state=random_seed)),
    ])

    print("[2/4] Train classifier has_case...", flush=True)
    classifier.fit(X_train, y_cls_train)
    cls_prob = classifier.predict_proba(X_test)[:, 1]
    cls_auc = float(roc_auc_score(y_cls_test, cls_prob))

    print("[3/4] Train regressor case_count...", flush=True)
    regressor.fit(X_train, y_reg_train)
    pred_cases = np.clip(np.expm1(regressor.predict(X_test)), 0, 1_000_000)
    true_cases = np.expm1(y_reg_test)
    mae = float(mean_absolute_error(true_cases, pred_cases))

    train_sample = X.sample(n=min(50000, len(X)), random_state=random_seed)
    sample_prob = classifier.predict_proba(train_sample)[:, 1]
    sample_cases = np.clip(np.expm1(regressor.predict(train_sample)), 0, 1_000_000)
    sample_score = sample_prob * np.log1p(sample_cases)
    quantiles = {
        "q50": float(np.quantile(sample_score, 0.50)),
        "q75": float(np.quantile(sample_score, 0.75)),
        "q90": float(np.quantile(sample_score, 0.90)),
    }

    disease_catalog = (
        dataset[["disease_group_id", "report_group_code", "disease_group_name"]]
        .drop_duplicates()
        .sort_values(["disease_group_id", "report_group_code", "disease_group_name"])
        .to_dict("records")
    )

    artifact = {
        "model_type": "weather_ai_risk_v1",
        "description": "Dự đoán top nhóm bệnh có nguy cơ ghi nhận ca cao theo thời tiết + nhóm tuổi + giới tính.",
        "sklearn_version": sklearn.__version__,
        "classifier": classifier,
        "regressor": regressor,
        "regression_target": "log1p_case_count",
        "feature_columns": FEATURE_COLUMNS,
        "categorical_features": CATEGORICAL_FEATURES,
        "numeric_features": NUMERIC_FEATURES,
        "weather_feature_columns": WEATHER_FEATURE_COLS,
        "disease_catalog": disease_catalog,
        "age_groups": sorted(dataset["age_group"].unique().tolist()),
        "genders": sorted(dataset["gender"].unique().tolist()),
        "risk_score_quantiles": quantiles,
        "training_summary": {
            "train_rows": int(len(dataset)),
            "positive_rows": int(dataset["has_case"].sum()),
            "negative_rows": int((dataset["has_case"] == 0).sum()),
            "total_case_count": int(dataset["case_count"].sum()),
            "disease_groups": int(dataset["disease_group_id"].nunique()),
            "weather_date_from": str(weather["date"].min().date()),
            "weather_date_to": str(weather["date"].max().date()),
            "patient_date_from": str(pd.to_datetime(dataset["date"]).min().date()),
            "patient_date_to": str(pd.to_datetime(dataset["date"]).max().date()),
            "negative_ratio": int(negative_ratio),
            "classifier_auc": cls_auc,
            "regressor_mae_cases": mae,
            **stats,
        },
    }

    output_model.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, output_model, compress=3)
    output_model.with_suffix(".summary.json").write_text(
        json.dumps(artifact["training_summary"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[4/4] Saved {output_model}", flush=True)
    return artifact["training_summary"]


def parse_args():
    parser = argparse.ArgumentParser(description="Train weather AI model")
    parser.add_argument("--weather-csv", default="Tool/weather/open-meteo-10.79N106.63E6m.csv")
    parser.add_argument("--train-history", default="Tool/weather/train_history.xlsx")
    parser.add_argument("--output-model", default="app/ml/weather_ai_risk_model.joblib")
    parser.add_argument("--negative-ratio", type=int, default=1)
    parser.add_argument("--random-seed", type=int, default=42)
    return parser.parse_args()


def main():
    args = parse_args()
    summary = train(
        weather_csv=Path(args.weather_csv),
        train_history=Path(args.train_history),
        output_model=Path(args.output_model),
        negative_ratio=args.negative_ratio,
        random_seed=args.random_seed,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
