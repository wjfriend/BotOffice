"""Model routing per bot: primary, fallback and price-first selection."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .client import LLMClient, LLMError
from .providers import Provider, ProviderRegistry

log = logging.getLogger(__name__)


@dataclass
class ModelBinding:
    """Which provider/model a bot uses.

    ``primary`` is the everyday model. ``fallback`` is tried when the primary
    fails. ``prefer_cheap`` lets the router pick the cheapest configured
    provider that exposes the requested model, which is the knob behind
    "use whichever platform is cheapest right now".
    """

    primary: str = ""
    fallback: str = ""
    prefer_cheap: bool = False
    budget_tokens: int = 8000
    extra: dict = field(default_factory=dict)


class ModelRouter:
    """Resolves a binding to a concrete provider and executes the call."""

    def __init__(self, registry: ProviderRegistry, client: LLMClient) -> None:
        self.registry = registry
        self.client = client

    def resolve(self, binding: ModelBinding, model_hint: str | None = None) -> Provider:
        """Pick the provider for a binding."""
        if binding.prefer_cheap:
            candidates = [
                p
                for p in self.registry.list()
                if model_hint is None or p.model == model_hint
            ]
            if candidates:
                return min(
                    candidates,
                    key=lambda p: p.cost_per_1k_input + p.cost_per_1k_output,
                )
        return self.registry.get(binding.primary)

    async def chat(
        self,
        binding: ModelBinding,
        system_prompt: str,
        messages: list[dict],
        *,
        model_hint: str | None = None,
        on_delta=None,
    ) -> tuple[str, str]:
        """Call the primary provider, falling back on failure.

        Returns ``(text, provider_id)`` so the caller can attribute cost.
        """
        attempts: list[str] = []
        if binding.primary:
            attempts.append(binding.primary)
        if binding.fallback and binding.fallback not in attempts:
            attempts.append(binding.fallback)

        if not attempts:
            raise LLMError("no model bound: set primary in the role configuration")

        last_error: Exception | None = None
        for provider_id in attempts:
            try:
                provider = self.registry.get(provider_id)
            except KeyError as exc:
                last_error = exc
                continue
            try:
                text = await self.client.chat(
                    provider, system_prompt, messages, on_delta=on_delta
                )
                return text, provider.id
            except LLMError as exc:
                last_error = exc
                log.warning("provider %s failed, trying next: %s", provider.id, exc)

        raise LLMError(f"all providers failed: {last_error}")
