from __future__ import annotations

from collections.abc import Generator

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.config import (
    GROQ_API_KEY,
    GROQ_MODEL,
    GROQ_TIMEOUT_SECONDS,
    MEDICAL_KNOWLEDGE_LLM_PROVIDER,
    MEDICAL_KNOWLEDGE_LLM_TIMEOUT_SECONDS,
    NCBI_API_KEY,
    NCBI_EMAIL,
    NCBI_TOOL,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OLLAMA_TIMEOUT_SECONDS,
    OPENAI_API_KEY,
    OPENAI_MODEL,
)
from app.models import User
from app.security import require_staff_or_admin
from app.services.medical_knowledge_draft_generator import (
    DraftGeneratorConfigurationError,
    DraftGeneratorError,
    DraftGeneratorOutputError,
    DraftGeneratorRateLimitError,
    DraftGeneratorTimeoutError,
    DraftGeneratorUnavailableError,
    MedicalKnowledgeDraftGenerator,
    GroqApiKeyMissingError,
    GroqAuthenticationError,
    GroqModelUnavailableError,
    OllamaModelNotInstalledError,
    OllamaModelNotSelectedError,
    create_medical_knowledge_draft_generator,
    get_medical_knowledge_llm_configuration,
)
from app.services.pubmed_client import (
    PubMedClient,
    PubMedConfigurationError,
    PubMedUnavailableError,
)


router = APIRouter(
    prefix="/api/medical-knowledge/service-status",
    tags=["Medical Knowledge Service Configuration"],
)


class PubMedServiceStatus(BaseModel):
    configured: bool
    email_configured: bool
    api_key_configured: bool


class LlmServiceStatus(BaseModel):
    configured: bool
    provider: str
    model: str | None
    api_key_configured: bool
    mode: str
    local: bool


class MedicalKnowledgeServiceStatus(BaseModel):
    pubmed: PubMedServiceStatus
    llm: LlmServiceStatus


class ConnectionTestResult(BaseModel):
    ok: bool
    message: str


def get_status_pubmed_client() -> Generator[PubMedClient, None, None]:
    client = PubMedClient(tool=NCBI_TOOL, email=NCBI_EMAIL, api_key=NCBI_API_KEY)
    try:
        yield client
    finally:
        client.close()


def get_status_llm_generator() -> Generator[MedicalKnowledgeDraftGenerator, None, None]:
    try:
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
        )
    except DraftGeneratorConfigurationError as exc:
        raise HTTPException(status_code=503, detail="Cấu hình nhà cung cấp AI không hợp lệ.") from exc
    try:
        yield generator
    finally:
        generator.close()


@router.get("", response_model=MedicalKnowledgeServiceStatus)
def get_service_status(_current_user: User = Depends(require_staff_or_admin)):
    llm = get_medical_knowledge_llm_configuration(
        provider=MEDICAL_KNOWLEDGE_LLM_PROVIDER,
        openai_api_key=OPENAI_API_KEY,
        openai_model=OPENAI_MODEL,
        ollama_base_url=OLLAMA_BASE_URL,
        ollama_model=OLLAMA_MODEL,
        groq_api_key=GROQ_API_KEY,
        groq_model=GROQ_MODEL,
    )
    return {
        "pubmed": {
            "configured": bool(NCBI_EMAIL),
            "email_configured": bool(NCBI_EMAIL),
            "api_key_configured": bool(NCBI_API_KEY),
        },
        "llm": {
            "configured": llm.configured,
            "provider": llm.provider,
            "model": llm.model,
            "api_key_configured": llm.api_key_configured,
            "mode": llm.mode,
            "local": llm.mode == "local",
        },
    }


@router.post("/pubmed/test", response_model=ConnectionTestResult)
def test_pubmed_connection(
    _current_user: User = Depends(require_staff_or_admin),
    client: PubMedClient = Depends(get_status_pubmed_client),
):
    try:
        client.search_ids('"public health"[Title/Abstract]', 1)
    except PubMedConfigurationError as exc:
        raise HTTPException(status_code=503, detail="PubMed chưa được cấu hình đầy đủ.") from exc
    except PubMedUnavailableError as exc:
        raise HTTPException(status_code=502, detail="Hiện không thể kết nối PubMed.") from exc
    return {"ok": True, "message": "Kết nối PubMed thành công."}


@router.post("/llm/test", response_model=ConnectionTestResult)
def test_llm_connection(
    _current_user: User = Depends(require_staff_or_admin),
    generator: MedicalKnowledgeDraftGenerator = Depends(get_status_llm_generator),
):
    try:
        generator.test_connection()
    except GroqApiKeyMissingError as exc:
        raise HTTPException(status_code=503, detail="Chưa cấu hình GROQ_API_KEY.") from exc
    except GroqAuthenticationError as exc:
        raise HTTPException(status_code=502, detail="Không thể xác thực với Groq.") from exc
    except GroqModelUnavailableError as exc:
        raise HTTPException(
            status_code=503, detail="Model Groq đã cấu hình không khả dụng."
        ) from exc
    except DraftGeneratorRateLimitError as exc:
        if MEDICAL_KNOWLEDGE_LLM_PROVIDER == "groq":
            detail = "Đã đạt giới hạn sử dụng Groq. Hãy thử lại sau."
        else:
            detail = "Đã đạt giới hạn sử dụng nhà cung cấp AI. Hãy thử lại sau."
        raise HTTPException(status_code=429, detail=detail) from exc
    except OllamaModelNotSelectedError as exc:
        raise HTTPException(status_code=503, detail="Chưa chọn model AI cục bộ.") from exc
    except OllamaModelNotInstalledError as exc:
        raise HTTPException(
            status_code=503, detail="Model AI cục bộ chưa được cài đặt trong Ollama."
        ) from exc
    except DraftGeneratorTimeoutError as exc:
        if MEDICAL_KNOWLEDGE_LLM_PROVIDER == "groq":
            detail = "Groq phản hồi quá lâu."
        elif MEDICAL_KNOWLEDGE_LLM_PROVIDER == "ollama":
            detail = "AI cục bộ phản hồi quá lâu."
        else:
            detail = "OpenAI phản hồi quá lâu."
        raise HTTPException(status_code=504, detail=detail) from exc
    except DraftGeneratorConfigurationError as exc:
        if MEDICAL_KNOWLEDGE_LLM_PROVIDER == "ollama":
            provider = "AI cục bộ Ollama"
        elif MEDICAL_KNOWLEDGE_LLM_PROVIDER == "groq":
            provider = "Groq"
        else:
            provider = "OpenAI"
        raise HTTPException(status_code=503, detail=f"{provider} chưa được cấu hình đầy đủ.") from exc
    except DraftGeneratorOutputError as exc:
        if MEDICAL_KNOWLEDGE_LLM_PROVIDER == "ollama":
            provider = "AI cục bộ"
        elif MEDICAL_KNOWLEDGE_LLM_PROVIDER == "groq":
            provider = "Groq"
        else:
            provider = "OpenAI"
        raise HTTPException(status_code=502, detail=f"{provider} trả dữ liệu không đúng định dạng.") from exc
    except DraftGeneratorUnavailableError as exc:
        if MEDICAL_KNOWLEDGE_LLM_PROVIDER == "ollama":
            detail = "Không kết nối được AI cục bộ Ollama. Hãy mở Ollama trên máy và thử lại."
        elif MEDICAL_KNOWLEDGE_LLM_PROVIDER == "groq":
            detail = "Hiện không thể kết nối Groq."
        else:
            detail = "Hiện không thể kết nối OpenAI."
        raise HTTPException(status_code=502, detail=detail) from exc
    except DraftGeneratorError as exc:
        raise HTTPException(status_code=502, detail="Hiện không thể kiểm tra nhà cung cấp AI.") from exc
    if MEDICAL_KNOWLEDGE_LLM_PROVIDER == "ollama":
        return {"ok": True, "message": "Kết nối AI cục bộ Ollama thành công."}
    if MEDICAL_KNOWLEDGE_LLM_PROVIDER == "groq":
        return {"ok": True, "message": "Kết nối Groq thành công."}
    return {"ok": True, "message": "Kết nối OpenAI thành công."}
