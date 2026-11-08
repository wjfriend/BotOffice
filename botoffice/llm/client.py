"""Unified LLM client: one call surface, three wire protocols.

The caller always speaks the same message format:

    messages = [{"role": "user", "content": "..."}, ...]
    response = await client.chat(provider, system_prompt, messages)

The client converts that into the provider's native format and converts the
reply back. Protocol choice is per provider, set by the user (constraint 5).
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from .providers import (
    PROTOCOL_ANTHROPIC,
    PROTOCOL_MOCK,
    PROTOCOL_OLLAMA,
    PROTOCOL_OPENAI,
    Provider,
    ProviderRegistry,
    UsageRecord,
)

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 120.0


class LLMError(RuntimeError):
    """Raised when a provider call fails in a way the caller must handle."""


class LLMClient:
    """Calls providers and records token usage and cost."""

    def __init__(self, registry: ProviderRegistry, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.registry = registry
        self.timeout = timeout

    async def chat(
        self,
        provider: Provider,
        system_prompt: str,
        messages: list[dict],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        """Send a chat request and return the assistant text."""
        if provider.protocol == PROTOCOL_OPENAI:
            payload, parse = self._build_openai(provider, system_prompt, messages, max_tokens, temperature)
            data = await self._post(provider, payload)
        elif provider.protocol == PROTOCOL_ANTHROPIC:
            payload, parse = self._build_anthropic(provider, system_prompt, messages, max_tokens, temperature)
            data = await self._post(provider, payload)
        elif provider.protocol == PROTOCOL_OLLAMA:
            payload, parse = self._build_ollama(provider, system_prompt, messages, max_tokens, temperature)
            data = await self._post(provider, payload)
        elif provider.protocol == PROTOCOL_MOCK:
            payload, parse = self._build_mock(provider, system_prompt, messages)
            data = payload
        else:
            raise LLMError(f"provider {provider.id}: unsupported protocol {provider.protocol!r}")
        text, input_tokens, output_tokens = parse(data)
        self.registry.record_usage(
            UsageRecord(
                provider_id=provider.id,
                model=provider.model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost=self._estimate_cost(provider, input_tokens, output_tokens),
                currency=provider.currency,
            )
        )
        return text

    # ---------------------------------------------------------------- build

    def _build_openai(
        self,
        provider: Provider,
        system_prompt: str,
        messages: list[dict],
        max_tokens: int | None,
        temperature: float | None,
    ) -> tuple[dict, Any]:
        wire: list[dict] = []
        if system_prompt:
            wire.append({"role": "system", "content": system_prompt})
        wire.extend({"role": m["role"], "content": m["content"]} for m in messages)
        payload: dict[str, Any] = {
            "model": provider.model,
            "messages": wire,
            "max_tokens": max_tokens or provider.max_tokens,
            "temperature": provider.temperature if temperature is None else temperature,
        }
        payload.update(provider.extra)

        def parse(data: dict) -> tuple[str, int, int]:
            choices = data.get("choices") or []
            if not choices:
                raise LLMError(f"provider {provider.id}: response has no choices: {str(data)[:200]}")
            message = choices[0].get("message") or {}
            text = message.get("content")
            if isinstance(text, list):
                # Some gateways return content as a list of parts.
                text = "".join(part.get("text", "") for part in text if isinstance(part, dict))
            usage = data.get("usage") or {}
            return (
                str(text or ""),
                int(usage.get("prompt_tokens") or 0),
                int(usage.get("completion_tokens") or 0),
            )

        return payload, parse

    def _build_anthropic(
        self,
        provider: Provider,
        system_prompt: str,
        messages: list[dict],
        max_tokens: int | None,
        temperature: float | None,
    ) -> tuple[dict, Any]:
        wire = [{"role": m["role"], "content": m["content"]} for m in messages]
        payload: dict[str, Any] = {
            "model": provider.model,
            "messages": wire,
            "max_tokens": max_tokens or provider.max_tokens,
            "temperature": provider.temperature if temperature is None else temperature,
        }
        if system_prompt:
            payload["system"] = system_prompt
        payload.update(provider.extra)

        def parse(data: dict) -> tuple[str, int, int]:
            blocks = data.get("content") or []
            text = "".join(b.get("text", "") for b in blocks if isinstance(b, dict))
            usage = data.get("usage") or {}
            return (
                text,
                int(usage.get("input_tokens") or 0),
                int(usage.get("output_tokens") or 0),
            )

        return payload, parse

    def _build_ollama(
        self,
        provider: Provider,
        system_prompt: str,
        messages: list[dict],
        max_tokens: int | None,
        temperature: float | None,
    ) -> tuple[dict, Any]:
        wire: list[dict] = []
        if system_prompt:
            wire.append({"role": "system", "content": system_prompt})
        wire.extend({"role": m["role"], "content": m["content"]} for m in messages)
        payload: dict[str, Any] = {
            "model": provider.model,
            "messages": wire,
            "stream": False,
            "options": {
                "temperature": provider.temperature if temperature is None else temperature,
            },
        }
        if max_tokens:
            payload["options"]["num_predict"] = max_tokens
        payload.update(provider.extra)

        def parse(data: dict) -> tuple[str, int, int]:
            message = data.get("message") or {}
            text = message.get("content") or data.get("response") or ""
            return (
                str(text),
                int(data.get("prompt_eval_count") or 0),
                int(data.get("eval_count") or 0),
            )

        return payload, parse

    def _build_mock(
        self,
        provider: Provider,
        system_prompt: str,
        messages: list[dict],
    ) -> tuple[dict, Any]:
        """Offline provider used for demos and tests.

        It answers with the JSON shape the agent loop expects, so the whole
        office can be exercised without an API key. The reply depends on the
        instruction so different interactions look different.
        """
        instruction = messages[-1]["content"] if messages else ""
        lowered = instruction.lower()

        if "decision" in lowered:
            if "new requirement" in lowered or "new_requirement" in lowered:
                decision = "new_requirement"
            elif "check" in lowered:
                decision = "check_current_task"
            else:
                decision = "keep_waiting"
            reply = {
                "decision": decision,
                "say": f"I would go with {decision.replace('_', ' ')}.",
            }
        elif "meeting" in lowered or "also present" in lowered:
            reply = {"say": "One point from me: we should agree on the next step today."}
        elif "hand" in lowered or "receiv" in lowered:
            reply = {"say": "Understood, I have it and will report back shortly."}
        elif "task" in lowered:
            reply = {"say": "Task accepted. First I will check the shared notes, then start."}
        else:
            reply = {"say": "Noted. I will keep working on it."}

        def parse(data: dict) -> tuple[str, int, int]:
            import json as _json

            text = _json.dumps(data["reply"], ensure_ascii=False)
            return text, len(system_prompt) // 4 + 1, len(text) // 4 + 1

        return {"reply": reply}, parse

    # ----------------------------------------------------------------- http

    async def _post(self, provider: Provider, payload: dict) -> dict:
        url = self._url(provider)
        headers = self._headers(provider)
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise LLMError(f"provider {provider.id}: request failed: {exc!r}") from exc

        if response.status_code != 200:
            raise LLMError(
                f"provider {provider.id}: HTTP {response.status_code}: {response.text[:300]}"
            )
        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise LLMError(f"provider {provider.id}: response is not JSON") from exc

    @staticmethod
    def _url(provider: Provider) -> str:
        base = provider.base_url.rstrip("/")
        if provider.protocol == PROTOCOL_OPENAI:
            return f"{base}/chat/completions"
        if provider.protocol == PROTOCOL_ANTHROPIC:
            return f"{base}/v1/messages" if not base.endswith("/messages") else base
        return f"{base}/api/chat"

    @staticmethod
    def _headers(provider: Provider) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if provider.protocol == PROTOCOL_ANTHROPIC:
            headers["x-api-key"] = provider.api_key
            headers["anthropic-version"] = "2023-06-01"
        elif provider.protocol == PROTOCOL_OPENAI:
            headers["Authorization"] = f"Bearer {provider.api_key}"
        return headers

    @staticmethod
    def _estimate_cost(provider: Provider, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens / 1000 * provider.cost_per_1k_input
            + output_tokens / 1000 * provider.cost_per_1k_output
        )
