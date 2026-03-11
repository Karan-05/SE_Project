"""LLM provider abstraction with caching and budget guardrails."""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

try:  # pragma: no cover - optional dependency
    import requests
except ImportError:  # pragma: no cover - soft dependency
    requests = None  # type: ignore

from src.config import PathConfig
from src.providers import cache

TRUE_VALUES = {"1", "true", "yes", "on"}


def _truthy(value: Optional[str], default: str = "0") -> bool:
    raw = default if value is None else value
    return raw.strip().lower() in TRUE_VALUES


@dataclass
class LLMRuntimeConfig:
    provider: str = os.getenv("LLM_PROVIDER", os.getenv("DECOMP_LLM_PROVIDER", "mock"))
    model: str = os.getenv("LLM_MODEL", "mock-model")
    temperature: float = float(os.getenv("LLM_TEMPERATURE", "0.25"))
    max_calls: Optional[int] = None
    max_tokens: Optional[int] = None
    budget_usd: Optional[float] = None
    cache_enabled: bool = True
    cache_dir: Path = field(default_factory=lambda: PathConfig().reports_root / "cache" / "llm")
    track_cost: bool = False
    timeout: int = 90


CONFIG = LLMRuntimeConfig()
CALLS_USED = 0
TOKENS_USED = 0
BUDGET_USED = 0.0


@dataclass
class LLMResponse:
    content: str
    tokens: int
    elapsed: float
    budget_exceeded: bool = False
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(
            {
                "content": self.content,
                "tokens": self.tokens,
                "elapsed": self.elapsed,
                "budget_exceeded": self.budget_exceeded,
                "meta": self.meta,
            }
        )

    @staticmethod
    def from_json(payload: str) -> "LLMResponse":
        data = json.loads(payload)
        return LLMResponse(
            content=data.get("content", ""),
            tokens=data.get("tokens", 0),
            elapsed=data.get("elapsed", 0.0),
            budget_exceeded=data.get("budget_exceeded", False),
            meta=data.get("meta", {}),
        )


def set_config(
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    cache_enabled: Optional[bool] = None,
    cache_dir: Optional[Path] = None,
    max_calls: Optional[int] = None,
    max_tokens: Optional[int] = None,
    budget_usd: Optional[float] = None,
    temperature: Optional[float] = None,
    timeout: Optional[int] = None,
) -> None:
    """Update global LLM configuration."""

    global CONFIG
    if provider:
        CONFIG.provider = provider
    if model:
        CONFIG.model = model
    if cache_enabled is not None:
        CONFIG.cache_enabled = cache_enabled
    if cache_dir is not None:
        CONFIG.cache_dir = cache_dir
    if max_calls is not None:
        CONFIG.max_calls = max_calls
    if max_tokens is not None:
        CONFIG.max_tokens = max_tokens
    if budget_usd is not None:
        CONFIG.budget_usd = budget_usd
    if temperature is not None:
        CONFIG.temperature = temperature
    if timeout is not None:
        CONFIG.timeout = timeout


def _cache_path(key: str) -> Path:
    target_dir = CONFIG.cache_dir / CONFIG.provider / CONFIG.model
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir / f"{key}.json"


def _budget_available(tokens: int) -> bool:
    if CONFIG.max_calls is not None and CALLS_USED >= CONFIG.max_calls:
        return False
    if CONFIG.max_tokens is not None and TOKENS_USED + tokens > CONFIG.max_tokens:
        return False
    if CONFIG.budget_usd is not None and BUDGET_USED >= CONFIG.budget_usd:
        return False
    return True


def _record_usage(tokens: int, elapsed: float, caller: str, cost: float = 0.0) -> None:
    global CALLS_USED, TOKENS_USED, BUDGET_USED
    CALLS_USED += 1
    TOKENS_USED += tokens
    BUDGET_USED += cost
    stats = cache.stats.setdefault("llm", {})
    caller_bucket = stats.setdefault(caller, {"tokens": 0.0, "time": 0.0, "calls": 0.0})
    caller_bucket["tokens"] += float(tokens)
    caller_bucket["time"] += float(elapsed)
    caller_bucket["calls"] += 1.0


def _hash_payload(payload: Dict[str, Any]) -> str:
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _openai_request(prompt: str, max_tokens: Optional[int], temperature: float) -> Tuple[str, int]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set.")
    try:
        from openai import OpenAI  # type: ignore
    except ImportError as exc:  # pragma: no cover - import guard
        raise RuntimeError("openai>=2.21.0 is required for the OpenAI provider.") from exc

    base_url = os.getenv("OPENAI_BASE_URL")
    configured_model = (CONFIG.model or "").strip()
    env_model = os.getenv("OPENAI_MODEL", "").strip()
    default_model = "gpt-5"
    if configured_model and configured_model != "mock-model":
        model = configured_model
    elif env_model:
        model = env_model
    else:
        model = default_model

    client_kwargs: Dict[str, Any] = {"api_key": api_key, "timeout": CONFIG.timeout}
    if base_url:
        client_kwargs["base_url"] = base_url.rstrip("/")
    client = OpenAI(**client_kwargs)

    requested_max = max_tokens if max_tokens is not None else 512
    if requested_max < 16:
        requested_max = 16
    request_payload = {
        "model": model,
        "input": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_output_tokens": requested_max,
    }

    def _extract_text(response: Any) -> str:
        text_blob = getattr(response, "output_text", None)
        if text_blob:
            return text_blob
        collected: list[str] = []
        for item in getattr(response, "output", []) or []:
            if getattr(item, "type", None) != "message":
                continue
            for block in getattr(item, "content", []) or []:
                if getattr(block, "type", None) != "output_text":
                    continue
                text_value = getattr(block, "text", "")
                if isinstance(text_value, list):
                    collected.append("".join(str(part) for part in text_value))
                elif text_value:
                    collected.append(str(text_value))
        return "".join(collected).strip()

    try:
        response = client.responses.create(**request_payload)
    except Exception as exc:  # pragma: no cover - depends on SDK/network
        status = getattr(exc, "status_code", None)
        error_response = getattr(exc, "response", None)
        response_text = ""
        if error_response is not None:
            try:
                response_text = error_response.text  # type: ignore[attr-defined]
            except Exception:
                try:
                    response_text = json.dumps(error_response.json())  # type: ignore[call-arg]
                except Exception:
                    response_text = repr(error_response)
        details = str(exc)
        if status or response_text:
            details = f"{details} (status={status or 'unknown'}, response={response_text})"
        raise RuntimeError(details) from exc

    content = _extract_text(response)
    usage = getattr(response, "usage", None)
    tokens = 0
    if usage is not None:
        tokens = int(getattr(usage, "total_tokens", 0) or 0)
    return content, tokens


def _azure_request(prompt: str, max_tokens: Optional[int], temperature: float) -> Tuple[str, int]:
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
    if not all([api_key, endpoint, deployment]):
        raise RuntimeError("Azure OpenAI configuration missing (AZURE_OPENAI_API_KEY/ENDPOINT/DEPLOYMENT).")
    if requests is None:  # pragma: no cover - optional dependency
        raise RuntimeError("requests is required for Azure OpenAI provider but is not installed.")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")
    url = f"{endpoint.rstrip('/')}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"
    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens or 512,
    }
    headers = {
        "api-key": api_key,
        "Content-Type": "application/json",
    }
    response = requests.post(url, headers=headers, json=payload, timeout=CONFIG.timeout)
    response.raise_for_status()
    data = response.json()
    content = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})
    tokens = int(usage.get("total_tokens", usage.get("completion_tokens", 0) + usage.get("prompt_tokens", 0)))
    return content, tokens


def _anthropic_request(prompt: str, max_tokens: Optional[int], temperature: float) -> Tuple[str, int]:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set.")
    if requests is None:  # pragma: no cover - optional dependency
        raise RuntimeError("requests is required for the Anthropic provider but is not installed.")
    model = CONFIG.model or os.getenv("ANTHROPIC_MODEL") or "claude-3-5-sonnet-20240620"
    url = "https://api.anthropic.com/v1/messages"
    payload = {
        "model": model,
        "max_tokens": max_tokens or 512,
        "temperature": temperature,
        "messages": [{"role": "user", "content": prompt}],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    response = requests.post(url, headers=headers, json=payload, timeout=CONFIG.timeout)
    response.raise_for_status()
    data = response.json()
    content = "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")
    usage = data.get("usage", {})
    tokens = int(usage.get("output_tokens", 0) + usage.get("input_tokens", 0))
    return content, tokens


def _mock_response(prompt: str, max_tokens: Optional[int], temperature: float) -> Tuple[str, int]:
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
    preview = prompt[:120].replace("\n", " ")
    content = f"[MOCK] {digest} :: {preview}"
    tokens = max(1, len(prompt.split()))
    return content, tokens


def _ollama_request(prompt: str, max_tokens: Optional[int], temperature: float) -> Tuple[str, int]:
    if requests is None:  # pragma: no cover - optional dependency
        raise RuntimeError("requests is required for the Ollama provider but is not installed.")
    base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    model = CONFIG.model or os.getenv("OLLAMA_MODEL") or "llama3"
    payload: Dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
        },
    }
    if max_tokens is not None:
        payload["options"]["num_predict"] = max_tokens
    response = requests.post(f"{base_url.rstrip('/')}/api/generate", json=payload, timeout=CONFIG.timeout)
    response.raise_for_status()
    data = response.json()
    content = data.get("response", "")
    tokens = int(data.get("eval_count", 0))
    return content, tokens


def _dispatch(prompt: str, max_tokens: Optional[int], temperature: float) -> Tuple[str, int]:
    provider = CONFIG.provider.lower()
    if provider == "openai":
        return _openai_request(prompt, max_tokens, temperature)
    if provider == "azure_openai":
        return _azure_request(prompt, max_tokens, temperature)
    if provider == "anthropic":
        return _anthropic_request(prompt, max_tokens, temperature)
    if provider == "ollama":
        return _ollama_request(prompt, max_tokens, temperature)
    if provider == "mock":
        return _mock_response(prompt, max_tokens, temperature)
    raise RuntimeError(f"Unsupported LLM provider '{CONFIG.provider}'.")


def call(
    prompt: str,
    model: Optional[str] = None,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    caller: Optional[str] = None,
    use_cache: bool = True,
    **kwargs: Any,
) -> LLMResponse:
    """Call the configured LLM provider (real or stub)."""

    provider = CONFIG.provider.lower()
    selected_model = model or CONFIG.model
    effective_temp = temperature if temperature is not None else CONFIG.temperature
    payload = {
        "provider": provider,
        "model": selected_model,
        "prompt": prompt,
        "max_tokens": max_tokens,
        "temperature": effective_temp,
        "caller": caller or "default",
        "extra": kwargs,
    }
    cache_key = _hash_payload(payload)
    if CONFIG.cache_enabled and use_cache:
        cached = _read_cache(cache_key)
        if cached:
            return cached
    tokens_estimate = max(1, len(prompt.split()))
    if not _budget_available(tokens_estimate):
        raise RuntimeError("LLM budget exceeded")
    start = time.perf_counter()
    content, tokens_used = _dispatch(prompt, max_tokens, effective_temp)
    elapsed = time.perf_counter() - start
    caller_name = caller or "default"
    _record_usage(tokens_used, elapsed, caller_name)
    response = LLMResponse(
        content=content,
        tokens=tokens_used,
        elapsed=elapsed,
        meta={"provider": provider, "model": selected_model, "caller": caller_name},
    )
    if CONFIG.cache_enabled and use_cache:
        _write_cache(cache_key, response)
    return response


def _read_cache(key: str) -> Optional[LLMResponse]:
    path = _cache_path(key)
    if not path.exists():
        return None
    try:
        return LLMResponse.from_json(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_cache(key: str, response: LLMResponse) -> None:
    path = _cache_path(key)
    try:
        path.write_text(response.to_json(), encoding="utf-8")
    except Exception:
        pass


def validate_connection(test_prompt: str = "Hello!") -> Tuple[bool, str, float, int]:
    """Run a cheap validation call."""

    try:
        response = call(test_prompt, max_tokens=8, temperature=0.01, caller="llm_validate", use_cache=False)
        if response.budget_exceeded:
            return False, "Budget exceeded before validation call.", response.elapsed, response.tokens
        return True, response.content.strip(), response.elapsed, response.tokens
    except Exception as exc:  # pragma: no cover - depends on provider
        return False, str(exc), 0.0, 0


def get_usage() -> Dict[str, Dict[str, float]]:
    """Return aggregate token/time usage."""

    per_caller = cache.stats.get("llm", {})
    return {
        "totals": {"tokens": TOKENS_USED, "calls": CALLS_USED, "budget": BUDGET_USED},
        "per_caller": per_caller,
    }


def total_calls() -> int:
    """Return the recorded number of provider invocations."""

    return CALLS_USED


__all__ = ["LLMResponse", "call", "get_usage", "set_config", "validate_connection", "total_calls"]
