from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from app.config import (
    AUTO_MEDICAL_KNOWLEDGE_AUTO_VISIBLE,
    AUTO_MEDICAL_KNOWLEDGE_GROQ_RATE_LIMIT_COOLDOWN_SECONDS,
    AUTO_MEDICAL_KNOWLEDGE_MAX_RETRIES,
    AUTO_MEDICAL_KNOWLEDGE_MAX_STRUCTURAL_RETRIES,
    AUTO_MEDICAL_KNOWLEDGE_PROMPT_VERSION,
    AUTO_MEDICAL_KNOWLEDGE_MAX_SOURCES,
    AUTO_MEDICAL_KNOWLEDGE_POLL_SECONDS,
    AUTO_MEDICAL_KNOWLEDGE_RESULTS_PER_SEARCH,
    AUTO_MEDICAL_KNOWLEDGE_RETRY_DELAY_SECONDS,
    AUTO_MEDICAL_KNOWLEDGE_SEARCHES_PER_TOPIC,
    GROQ_API_KEY,
    GROQ_MODEL,
    GROQ_TIMEOUT_SECONDS,
    MEDICAL_KNOWLEDGE_LLM_MAX_INPUT_CHARS,
    MEDICAL_KNOWLEDGE_LLM_PROVIDER,
    MEDICAL_KNOWLEDGE_LLM_TIMEOUT_SECONDS,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OLLAMA_TIMEOUT_SECONDS,
    OPENAI_API_KEY,
    OPENAI_MODEL,
    WEATHER_AI_V3_DISEASE_CATALOG,
    WEATHER_AI_V3_MODEL_MANIFEST,
)
from app.database import SessionLocal
from app.services.auto_evidence_discovery import PubMedAutoEvidenceProvider
from app.services.auto_medical_knowledge_prompt import (
    AUTO_SYSTEM_INSTRUCTIONS,
    BASIC_AUTO_SYSTEM_INSTRUCTIONS,
    build_auto_generation_input,
    build_auto_basic_generation_input,
)
from app.services.auto_medical_knowledge_service import AutoMedicalKnowledgeProcessor
from app.auto_medical_knowledge_schemas import (
    AutoBasicMedicalKnowledgeProposal,
    AutoMedicalKnowledgeDraftProposal,
)
from app.repositories.auto_medical_knowledge_repository import AutoMedicalKnowledgeRepository
from app.services.medical_evidence_provider_factory import (
    create_medical_evidence_provider_registry,
)
from app.services.medical_knowledge_draft_generator import (
    create_medical_knowledge_draft_generator,
)


logger = logging.getLogger(__name__)


def recover_interrupted_auto_medical_knowledge_jobs() -> int:
    """Run once before workers start; never while concurrent workers are active."""
    with SessionLocal() as db:
        count = AutoMedicalKnowledgeRepository(db).recover_interrupted_jobs(
            now=datetime.utcnow()
        )
        db.commit()
        return count


def process_auto_medical_knowledge_once() -> bool:
    # Cheap persisted control-plane check before constructing any provider.
    # The claim statement checks the same setting again to close toggle races.
    try:
        with SessionLocal() as db:
            repository = AutoMedicalKnowledgeRepository(db)
            if not repository.is_runtime_enabled():
                return False
            if repository.get_active_provider_cooldown(
                MEDICAL_KNOWLEDGE_LLM_PROVIDER, now=datetime.utcnow()
            ) is not None:
                return False
    except Exception:
        logger.exception("Auto Medical Knowledge runtime setting could not be read")
        return False
    provider_registry = create_medical_evidence_provider_registry()
    generator = create_medical_knowledge_draft_generator(
        provider=MEDICAL_KNOWLEDGE_LLM_PROVIDER,
        openai_api_key=OPENAI_API_KEY,
        openai_model=OPENAI_MODEL,
        openai_timeout_seconds=MEDICAL_KNOWLEDGE_LLM_TIMEOUT_SECONDS,
        ollama_base_url=OLLAMA_BASE_URL,
        ollama_model=OLLAMA_MODEL,
        ollama_timeout_seconds=OLLAMA_TIMEOUT_SECONDS,
        groq_api_key=GROQ_API_KEY,
        groq_model=GROQ_MODEL,
        groq_timeout_seconds=GROQ_TIMEOUT_SECONDS,
        system_instructions=AUTO_SYSTEM_INSTRUCTIONS,
        input_builder=build_auto_generation_input,
        proposal_model=AutoMedicalKnowledgeDraftProposal,
    )
    basic_generator = create_medical_knowledge_draft_generator(
        provider=MEDICAL_KNOWLEDGE_LLM_PROVIDER,
        openai_api_key=OPENAI_API_KEY,
        openai_model=OPENAI_MODEL,
        openai_timeout_seconds=MEDICAL_KNOWLEDGE_LLM_TIMEOUT_SECONDS,
        ollama_base_url=OLLAMA_BASE_URL,
        ollama_model=OLLAMA_MODEL,
        ollama_timeout_seconds=OLLAMA_TIMEOUT_SECONDS,
        groq_api_key=GROQ_API_KEY,
        groq_model=GROQ_MODEL,
        groq_timeout_seconds=GROQ_TIMEOUT_SECONDS,
        system_instructions=BASIC_AUTO_SYSTEM_INSTRUCTIONS,
        input_builder=build_auto_basic_generation_input,
        proposal_model=AutoBasicMedicalKnowledgeProposal,
    )
    try:
        with SessionLocal() as db:
            discovery = PubMedAutoEvidenceProvider(
                provider_registry.get("PUBMED"),
                searches_per_topic=AUTO_MEDICAL_KNOWLEDGE_SEARCHES_PER_TOPIC,
                results_per_search=AUTO_MEDICAL_KNOWLEDGE_RESULTS_PER_SEARCH,
            )
            processor = AutoMedicalKnowledgeProcessor(
                db,
                discovery,
                generator,
                basic_generator,
                disease_manifest_path=WEATHER_AI_V3_MODEL_MANIFEST,
                disease_catalog_path=WEATHER_AI_V3_DISEASE_CATALOG,
                max_sources=AUTO_MEDICAL_KNOWLEDGE_MAX_SOURCES,
                max_retries=AUTO_MEDICAL_KNOWLEDGE_MAX_RETRIES,
                max_structural_retries=AUTO_MEDICAL_KNOWLEDGE_MAX_STRUCTURAL_RETRIES,
                retry_delay_seconds=AUTO_MEDICAL_KNOWLEDGE_RETRY_DELAY_SECONDS,
                provider_name=MEDICAL_KNOWLEDGE_LLM_PROVIDER,
                rate_limit_cooldown_seconds=(
                    AUTO_MEDICAL_KNOWLEDGE_GROQ_RATE_LIMIT_COOLDOWN_SECONDS
                ),
                prompt_version=AUTO_MEDICAL_KNOWLEDGE_PROMPT_VERSION,
                auto_visible_default=AUTO_MEDICAL_KNOWLEDGE_AUTO_VISIBLE,
                max_input_chars=MEDICAL_KNOWLEDGE_LLM_MAX_INPUT_CHARS,
            )
            return processor.process_next() is not None
    finally:
        provider_registry.close()
        generator.close()
        basic_generator.close()


async def run_auto_medical_knowledge_worker(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            processed = await asyncio.to_thread(process_auto_medical_knowledge_once)
        except Exception:
            logger.exception("Auto Medical Knowledge worker iteration failed before claiming a job")
            processed = False
        if processed:
            continue
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=AUTO_MEDICAL_KNOWLEDGE_POLL_SECONDS)
        except TimeoutError:
            pass
