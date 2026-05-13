"""LLM-native schemas for company enrichment JSON (Gemini, OpenAI strict mode, Ollama format)."""

from __future__ import annotations

from typing import Any

# Gemini `GenerationConfig.responseSchema` (Schema proto JSON; types are UPPERCASE).
GEMINI_COMPANY_ENRICHMENT_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "Name": {"type": "STRING"},
        "Industry": {"type": "ARRAY", "items": {"type": "STRING"}},
        "current_use_of_AI": {"type": "STRING"},
        "possible_use_of_AI": {"type": "STRING"},
        "avoid_AI_use": {"type": "STRING"},
    },
    "required": [
        "Name",
        "Industry",
        "current_use_of_AI",
        "possible_use_of_AI",
        "avoid_AI_use",
    ],
    "propertyOrdering": [
        "Name",
        "Industry",
        "current_use_of_AI",
        "possible_use_of_AI",
        "avoid_AI_use",
    ],
}

# OpenAI Chat Completions `response_format.json_schema` and Ollama `/api/chat` `format` (JSON Schema).
OPENAI_COMPANY_ENRICHMENT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "Name": {"type": "string"},
        "Industry": {"type": "array", "items": {"type": "string"}},
        "current_use_of_AI": {"type": "string"},
        "possible_use_of_AI": {"type": "string"},
        "avoid_AI_use": {"type": "string"},
    },
    "required": [
        "Name",
        "Industry",
        "current_use_of_AI",
        "possible_use_of_AI",
        "avoid_AI_use",
    ],
}
