from __future__ import annotations

import pytest
from langchain_openai import ChatOpenAI

from tribos.utils.llm.llm_factory import (
    DEFAULT_ORCHESTRATOR_MODEL,
    LLMUnavailableError,
    get_llm,
    get_supported_models,
    is_allowed_model,
)


def test_muse_spark_is_default_and_allowed() -> None:
    assert DEFAULT_ORCHESTRATOR_MODEL == "muse-spark-1.3"
    assert is_allowed_model("muse-spark-1.3")
    catalog = get_supported_models()
    muse_entry = next((m for m in catalog if m["id"] == "muse-spark-1.3"), None)
    assert muse_entry is not None
    assert muse_entry["provider"] == "meta"
    assert muse_entry["is_default"] is True


def test_muse_spark_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("META_API_KEY", raising=False)
    with pytest.raises(LLMUnavailableError, match="No API key configured for model 'muse-spark-1.3'"):
        get_llm(model_name="muse-spark-1.3", api_key=None)


def test_muse_spark_initialization_with_env_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("META_API_KEY", "LLM_fake_test_key_12345")
    llm = get_llm(model_name="muse-spark-1.3")
    assert isinstance(llm, ChatOpenAI)
    assert llm.model_name == "muse-spark-1.3"
    assert "api.meta.ai" in str(llm.openai_api_base or "")


def test_muse_spark_initialization_with_caller_key() -> None:
    llm = get_llm(model_name="muse-spark-1.3", api_key="LLM_explicit_caller_key")
    assert isinstance(llm, ChatOpenAI)
    assert llm.model_name == "muse-spark-1.3"
    assert "api.meta.ai" in str(llm.openai_api_base or "")
