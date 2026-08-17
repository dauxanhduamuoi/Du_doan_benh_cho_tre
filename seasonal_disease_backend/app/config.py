import os
from pathlib import Path

# JWT
SECRET_KEY = os.getenv("SECRET_KEY", "CHANGE_THIS_SECRET_KEY_FOR_PRODUCTION")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "480"))

# Weather Disease AI V3 runtime. Paths are centralized here so services and routes
# do not carry repository-relative constants of their own.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parent
WEATHER_AI_V3_ROOT = Path(
    os.getenv("WEATHER_AI_V3_ROOT", str(REPOSITORY_ROOT / "weather_disease_ai_v3"))
).resolve()
WEATHER_AI_V3_DEPLOYMENT_DIR = Path(
    os.getenv(
        "WEATHER_AI_V3_DEPLOYMENT_DIR",
        str(WEATHER_AI_V3_ROOT / "deployment" / "lightgbm_h14_weather"),
    )
).resolve()
WEATHER_AI_V3_MODEL_MANIFEST = Path(
    os.getenv(
        "WEATHER_AI_V3_MODEL_MANIFEST",
        str(WEATHER_AI_V3_DEPLOYMENT_DIR / "model_manifest.json"),
    )
).resolve()
WEATHER_AI_V3_FEATURE_SCHEMA = Path(
    os.getenv(
        "WEATHER_AI_V3_FEATURE_SCHEMA",
        str(WEATHER_AI_V3_DEPLOYMENT_DIR / "feature_schema.json"),
    )
).resolve()
WEATHER_AI_V3_CATEGORY_MAPPINGS = Path(
    os.getenv(
        "WEATHER_AI_V3_CATEGORY_MAPPINGS",
        str(WEATHER_AI_V3_DEPLOYMENT_DIR / "category_mappings.json"),
    )
).resolve()
WEATHER_AI_V3_DISEASE_CATALOG = Path(
    os.getenv(
        "WEATHER_AI_V3_DISEASE_CATALOG",
        str(WEATHER_AI_V3_ROOT / "data" / "processed" / "disease_catalog.csv"),
    )
).resolve()
WEATHER_AI_V3_MEDICAL_KB = Path(
    os.getenv(
        "WEATHER_AI_V3_MEDICAL_KB",
        str(
            WEATHER_AI_V3_ROOT
            / "medical_explainability"
            / "lightgbm_h14"
            / "medical_knowledge_base.json"
        ),
    )
).resolve()
WEATHER_AI_V3_EXPECTED_MODEL_COUNT = int(
    os.getenv("WEATHER_AI_V3_EXPECTED_MODEL_COUNT", "221")
)
WEATHER_AI_V3_PRELOAD = os.getenv("WEATHER_AI_V3_PRELOAD", "1").strip().lower() not in {
    "0",
    "false",
    "no",
}
