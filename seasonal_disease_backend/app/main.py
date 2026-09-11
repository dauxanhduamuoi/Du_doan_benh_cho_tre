import os
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, SessionLocal, engine
from app import medical_knowledge_models  # noqa: F401 - register tables in Base metadata
from app.routers import (
    admin,
    auto_medical_knowledge,
    areas,
    auth,
    dashboard,
    forecast,
    import_data,
    medical_knowledge_drafts,
    medical_knowledge_pubmed,
    medical_knowledge_service_status,
    public,
    reports,
    weather_ai,
)
from app.services.area_service import ensure_area_schema, seed_default_areas
from app.config import (
    AUTO_MEDICAL_KNOWLEDGE_MAX_CONCURRENT_JOBS,
    WEATHER_AI_V3_PRELOAD,
    validate_security_configuration,
)
from app.services.auto_medical_knowledge_worker import (
    recover_interrupted_auto_medical_knowledge_jobs,
    run_auto_medical_knowledge_worker,
)
from app.services.weather_ai_service import initialize_weather_ai_runtime
from migrations.v002_medical_evidence_content import upgrade as upgrade_medical_evidence_content
from migrations.v003_medical_knowledge_publication import upgrade as upgrade_medical_publication
from migrations.v004_medical_knowledge_unpublish import upgrade as upgrade_medical_unpublish
from migrations.v005_medical_knowledge_topic_sources import upgrade as upgrade_medical_topic_sources
from migrations.v006_medical_knowledge_pediatric_population import (
    upgrade as upgrade_medical_pediatric_population,
)
from migrations.v007_medical_knowledge_general_factors import (
    upgrade as upgrade_medical_general_factors,
)
from migrations.v008_auto_medical_knowledge import upgrade as upgrade_auto_medical_knowledge
from migrations.v009_auto_medical_knowledge_runtime_toggle import (
    upgrade as upgrade_auto_medical_knowledge_runtime_toggle,
)
from migrations.v010_auto_medical_knowledge_provider_cooldown import (
    upgrade as upgrade_auto_medical_knowledge_provider_cooldown,
)
from migrations.v011_auto_numeric_claim_contract import (
    upgrade as upgrade_auto_numeric_claim_contract,
)
from migrations.v012_auto_safe_fallback import upgrade as upgrade_auto_safe_fallback
from migrations.v013_auto_multi_tier_generation import (
    upgrade as upgrade_auto_multi_tier_generation,
)
from migrations.v014_auto_topic_visibility import upgrade as upgrade_auto_topic_visibility
from migrations.v015_medical_evidence_providers import (
    upgrade as upgrade_medical_evidence_providers,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_security_configuration()
    Base.metadata.create_all(bind=engine)
    upgrade_medical_evidence_content(engine)
    upgrade_medical_publication(engine)
    upgrade_medical_unpublish(engine)
    upgrade_medical_topic_sources(engine)
    upgrade_medical_pediatric_population(engine)
    upgrade_medical_general_factors(engine)
    upgrade_auto_medical_knowledge(engine)
    upgrade_auto_medical_knowledge_runtime_toggle(engine)
    upgrade_auto_medical_knowledge_provider_cooldown(engine)
    upgrade_auto_numeric_claim_contract(engine)
    upgrade_auto_safe_fallback(engine)
    upgrade_auto_multi_tier_generation(engine)
    upgrade_auto_topic_visibility(engine)
    upgrade_medical_evidence_providers(engine)
    ensure_area_schema(engine)
    with SessionLocal() as db:
        seed_default_areas(db)
    if WEATHER_AI_V3_PRELOAD:
        status = initialize_weather_ai_runtime()
        if not status.get("ready"):
            raise RuntimeError(f"Weather AI V3 preload failed: {status.get('error')}")
    recover_interrupted_auto_medical_knowledge_jobs()
    stop_event = asyncio.Event()
    workers = [
        asyncio.create_task(run_auto_medical_knowledge_worker(stop_event))
        for _ in range(AUTO_MEDICAL_KNOWLEDGE_MAX_CONCURRENT_JOBS)
    ]
    try:
        yield
    finally:
        stop_event.set()
        if workers:
            await asyncio.gather(*workers, return_exceptions=True)

app = FastAPI(
    title="Seasonal Disease Forecast API",
    description="Backend cho hệ thống phân tích dữ liệu bệnh nhi theo mùa vụ.",
    version="0.1.0",
    lifespan=lifespan,
)

cors_origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ALLOW_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174",
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {
        "message": "Seasonal Disease Forecast API is running.",
        "docs": "/docs"
    }

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(import_data.router)
app.include_router(dashboard.router)
app.include_router(forecast.router)
app.include_router(public.router)
app.include_router(reports.router)
app.include_router(weather_ai.router)
app.include_router(areas.router)
app.include_router(medical_knowledge_pubmed.router)
app.include_router(medical_knowledge_pubmed.options_router)
app.include_router(medical_knowledge_drafts.router)
app.include_router(medical_knowledge_service_status.router)
app.include_router(auto_medical_knowledge.router)
