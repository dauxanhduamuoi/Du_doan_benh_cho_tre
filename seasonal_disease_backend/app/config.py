import os
from pathlib import Path

from dotenv import load_dotenv


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parent
BACKEND_ENV_FILE = BACKEND_ROOT / ".env"


def load_backend_environment(env_file: Path = BACKEND_ENV_FILE) -> bool:
    """Load the canonical backend .env without overriding real environment values."""

    return load_dotenv(dotenv_path=env_file, override=False)


load_backend_environment()

# JWT
SECRET_KEY = os.getenv("SECRET_KEY", "").strip()
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "480"))


def validate_security_configuration() -> None:
    """Fail closed before serving requests with a missing or weak JWT signing key."""

    if len(SECRET_KEY) < 32:
        raise RuntimeError(
            "SECRET_KEY must be configured with at least 32 characters before startup"
        )


# Weather Disease AI V3 runtime. Paths are centralized here so services and routes
# do not carry repository-relative constants of their own.
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

# NCBI E-utilities. Email is intentionally required only when a PubMed request is
# made so missing optional integration config never prevents application startup.
NCBI_TOOL = os.getenv("NCBI_TOOL", "weather_ai_v3_medical_knowledge").strip()
NCBI_EMAIL = os.getenv("NCBI_EMAIL", "").strip() or None
NCBI_API_KEY = os.getenv("NCBI_API_KEY", "").strip() or None

# Medical Knowledge draft generation. Optional provider configuration is read at
# startup, but it is validated only when draft generation is requested so the
# rest of Weather AI and PubMed remain available without an LLM integration.
MEDICAL_KNOWLEDGE_LLM_PROVIDER = os.getenv(
    "MEDICAL_KNOWLEDGE_LLM_PROVIDER", "ollama"
).strip().lower()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip() or None
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b").strip() or None
GROQ_TIMEOUT_SECONDS = float(os.getenv("GROQ_TIMEOUT_SECONDS", "45"))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip() or None
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "").strip() or None
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").strip()
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "").strip() or None
OLLAMA_TIMEOUT_SECONDS = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "120"))
MEDICAL_KNOWLEDGE_PROMPT_VERSION = os.getenv(
    "MEDICAL_KNOWLEDGE_PROMPT_VERSION", "medical_knowledge_v4_general_factors"
).strip()
MEDICAL_KNOWLEDGE_LLM_TIMEOUT_SECONDS = float(
    os.getenv("MEDICAL_KNOWLEDGE_LLM_TIMEOUT_SECONDS", "45")
)
MEDICAL_KNOWLEDGE_LLM_MAX_INPUT_CHARS = int(
    os.getenv("MEDICAL_KNOWLEDGE_LLM_MAX_INPUT_CHARS", "60000")
)
MEDICAL_KNOWLEDGE_LLM_MAX_SOURCES = int(
    os.getenv("MEDICAL_KNOWLEDGE_LLM_MAX_SOURCES", "10")
)
MEDICAL_KNOWLEDGE_EVIDENCE_MAX_CHARS_PER_SOURCE = int(
    os.getenv("MEDICAL_KNOWLEDGE_EVIDENCE_MAX_CHARS_PER_SOURCE", "6000")
)

# WHO Publications is a public, unauthenticated official source. These bounds
# are transport safety controls, not feature enablement settings.
WHO_EVIDENCE_TIMEOUT_SECONDS = min(
    30.0, max(1.0, float(os.getenv("WHO_EVIDENCE_TIMEOUT_SECONDS", "15")))
)
WHO_EVIDENCE_MAX_RESPONSE_BYTES = min(
    5_000_000,
    max(1024, int(os.getenv("WHO_EVIDENCE_MAX_RESPONSE_BYTES", "2000000"))),
)

# Auto runtime ON/OFF is persisted in the database and controlled by Admin UI.
# These settings remain separate controls for display and worker bounds.
AUTO_MEDICAL_KNOWLEDGE_DISPLAY_MODE = os.getenv(
    "AUTO_MEDICAL_KNOWLEDGE_DISPLAY_MODE", "REVIEWED_ONLY"
).strip().upper()
AUTO_MEDICAL_KNOWLEDGE_MAX_SOURCES = min(
    10, max(1, int(os.getenv("AUTO_MEDICAL_KNOWLEDGE_MAX_SOURCES", "10")))
)
AUTO_MEDICAL_KNOWLEDGE_MAX_CONCURRENT_JOBS = min(
    4, max(1, int(os.getenv("AUTO_MEDICAL_KNOWLEDGE_MAX_CONCURRENT_JOBS", "1")))
)
AUTO_MEDICAL_KNOWLEDGE_MAX_RETRIES = max(
    1, int(os.getenv("AUTO_MEDICAL_KNOWLEDGE_MAX_RETRIES", "3"))
)
AUTO_MEDICAL_KNOWLEDGE_MAX_STRUCTURAL_RETRIES = min(
    1, max(0, int(os.getenv("AUTO_MEDICAL_KNOWLEDGE_MAX_STRUCTURAL_RETRIES", "1")))
)
AUTO_MEDICAL_KNOWLEDGE_RETRY_DELAY_SECONDS = max(
    1, int(os.getenv("AUTO_MEDICAL_KNOWLEDGE_RETRY_DELAY_SECONDS", "300"))
)
AUTO_MEDICAL_KNOWLEDGE_GROQ_RATE_LIMIT_COOLDOWN_SECONDS = max(
    1,
    int(
        os.getenv(
            "AUTO_MEDICAL_KNOWLEDGE_GROQ_RATE_LIMIT_COOLDOWN_SECONDS", "300"
        )
    ),
)
AUTO_MEDICAL_KNOWLEDGE_POLL_SECONDS = max(
    1.0, float(os.getenv("AUTO_MEDICAL_KNOWLEDGE_POLL_SECONDS", "5"))
)
AUTO_MEDICAL_KNOWLEDGE_INSUFFICIENT_STALE_DAYS = max(
    1, int(os.getenv("AUTO_MEDICAL_KNOWLEDGE_INSUFFICIENT_STALE_DAYS", "30"))
)
AUTO_MEDICAL_KNOWLEDGE_AUTO_VISIBLE = os.getenv(
    "AUTO_MEDICAL_KNOWLEDGE_AUTO_VISIBLE", "0"
).strip().lower() in {"1", "true", "yes"}
AUTO_MEDICAL_KNOWLEDGE_PROMPT_VERSION = os.getenv(
    "AUTO_MEDICAL_KNOWLEDGE_PROMPT_VERSION",
    "medical_knowledge_auto_v2_numeric_claims",
).strip()
if not AUTO_MEDICAL_KNOWLEDGE_PROMPT_VERSION.startswith(
    "medical_knowledge_auto_v2_numeric_claims"
):
    AUTO_MEDICAL_KNOWLEDGE_PROMPT_VERSION = "medical_knowledge_auto_v2_numeric_claims"
AUTO_MEDICAL_KNOWLEDGE_SEARCHES_PER_TOPIC = min(
    3, max(1, int(os.getenv("AUTO_MEDICAL_KNOWLEDGE_SEARCHES_PER_TOPIC", "3")))
)
AUTO_MEDICAL_KNOWLEDGE_RESULTS_PER_SEARCH = min(
    25, max(1, int(os.getenv("AUTO_MEDICAL_KNOWLEDGE_RESULTS_PER_SEARCH", "15")))
)
