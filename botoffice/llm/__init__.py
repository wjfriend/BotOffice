"""LLM layer: provider registry, unified client and model router."""

from .client import LLMClient, LLMError
from .providers import (
    PROTOCOL_ANTHROPIC,
    PROTOCOL_OLLAMA,
    PROTOCOL_OPENAI,
    PROTOCOLS,
    Provider,
    ProviderRegistry,
    UsageRecord,
)
from .router import ModelBinding, ModelRouter

__all__ = [
    "LLMClient",
    "LLMError",
    "ModelBinding",
    "ModelRouter",
    "PROTOCOLS",
    "PROTOCOL_ANTHROPIC",
    "PROTOCOL_OLLAMA",
    "PROTOCOL_OPENAI",
    "Provider",
    "ProviderRegistry",
    "UsageRecord",
]
