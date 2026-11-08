"""LLM provider registry.

A provider is described entirely by configuration: protocol, base URL, key,
model and price. Nothing here is hardcoded to a specific vendor, so the user
can add any OpenAI-compatible endpoint, any Anthropic-compatible endpoint, or
a local Ollama instance (constraint 5 in CLAUDE.md).
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

PROTOCOL_OPENAI = "openai"
PROTOCOL_ANTHROPIC = "anthropic"
PROTOCOL_OLLAMA = "ollama"
PROTOCOL_MOCK = "mock"
PROTOCOLS = (PROTOCOL_OPENAI, PROTOCOL_ANTHROPIC, PROTOCOL_OLLAMA, PROTOCOL_MOCK)


@dataclass
class Provider:
    """One LLM platform the user configured."""

    id: str
    protocol: str = PROTOCOL_OPENAI
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    label: str = ""
    short: str = ""
    currency: str = "CNY"
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0
    max_tokens: int = 4096
    temperature: float = 0.7
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.protocol not in PROTOCOLS:
            raise ValueError(
                f"provider {self.id}: unknown protocol {self.protocol!r}, "
                f"expected one of {PROTOCOLS}"
            )
        if self.protocol != PROTOCOL_MOCK and not self.base_url:
            raise ValueError(f"provider {self.id}: base_url is required")
        if self.protocol not in (PROTOCOL_OLLAMA, PROTOCOL_MOCK) and not self.api_key:
            raise ValueError(f"provider {self.id}: api_key is required for {self.protocol}")
        if not self.model:
            raise ValueError(f"provider {self.id}: model is required")
        if not self.label:
            self.label = self.id
        if not self.short:
            # A compact code shown on the character name tag, e.g. DSF.
            self.short = self.id[:3].upper()

    @property
    def requires_key(self) -> bool:
        return self.protocol not in (PROTOCOL_OLLAMA, PROTOCOL_MOCK)

    def redacted(self) -> dict:
        """Serialisable view with the key masked, for API responses and logs."""
        data = asdict(self)
        if data.get("api_key"):
            data["api_key"] = "***"
        return data


@dataclass
class UsageRecord:
    """Token and money accounting for one call."""

    provider_id: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    currency: str = "CNY"
    ts: float = field(default_factory=time.time)

    def as_dict(self) -> dict:
        return {
            "provider_id": self.provider_id,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost": round(self.cost, 6),
            "currency": self.currency,
            "ts": round(self.ts, 3),
        }


class ProviderRegistry:
    """Thread-safe registry of providers plus per-provider usage totals."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else None
        self._lock = threading.RLock()
        self._providers: dict[str, Provider] = {}
        self._usage: list[UsageRecord] = []

    def load(self) -> None:
        """Load providers from the JSON config file if it exists."""
        if not self.path or not self.path.exists():
            return
        raw = json.loads(self.path.read_text(encoding="utf-8") or "{}")
        with self._lock:
            self._providers.clear()
            for item in raw.get("providers", []):
                item = dict(item)
                item.setdefault("api_key", "")
                item["api_key"] = os.environ.get(item["api_key"], "") if item["api_key"].startswith("$") else item["api_key"]
                provider = Provider(**item)
                self._providers[provider.id] = provider

    def save(self) -> None:
        """Persist providers, writing API keys as ${ENV_VAR} placeholders."""
        if not self.path:
            return
        payload = {"providers": []}
        for provider in self._providers.values():
            data = asdict(provider)
            if provider.api_key:
                data["api_key"] = f"${{{provider.id.upper()}_API_KEY}}"
            payload["providers"].append(data)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        import os
        import tempfile

        fd, tmp_name = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, indent=2))
            os.replace(tmp_name, self.path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    def add(self, provider: Provider) -> Provider:
        with self._lock:
            self._providers[provider.id] = provider
        self.save()
        return provider

    def remove(self, provider_id: str) -> bool:
        with self._lock:
            existed = self._providers.pop(provider_id, None) is not None
        if existed:
            self.save()
        return existed

    def get(self, provider_id: str) -> Provider:
        with self._lock:
            provider = self._providers.get(provider_id)
        if provider is None:
            known = sorted(self._providers)
            raise KeyError(f"unknown provider {provider_id!r}; known: {known}")
        return provider

    def list(self) -> list[Provider]:
        with self._lock:
            return list(self._providers.values())

    def record_usage(self, record: UsageRecord) -> None:
        with self._lock:
            self._usage.append(record)

    def usage_records(self) -> list[UsageRecord]:
        with self._lock:
            return list(self._usage)

    def cost_summary(self) -> list[dict]:
        """Aggregate spend per provider and per model."""
        totals: dict[tuple[str, str], dict] = {}
        for record in self.usage_records():
            key = (record.provider_id, record.model)
            row = totals.setdefault(
                key,
                {
                    "provider_id": record.provider_id,
                    "model": record.model,
                    "calls": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cost": 0.0,
                    "currency": record.currency,
                },
            )
            row["calls"] += 1
            row["input_tokens"] += record.input_tokens
            row["output_tokens"] += record.output_tokens
            row["cost"] = round(row["cost"] + record.cost, 6)
        return sorted(totals.values(), key=lambda row: row["cost"], reverse=True)

    def total_cost(self) -> float:
        return round(sum(row["cost"] for row in self.cost_summary()), 6)
