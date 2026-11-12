"""Instruction-based constraint extraction with optional LLM structured parsing and regex fallback."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

logger = logging.getLogger("mandate.constraints")

DEFAULT_MODEL = "openai/gpt-oss-20b"
BACKOFF_DELAYS = (1.0, 3.0)
REQUEST_TIMEOUT = 45.0


class ExtractedConstraint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str = Field(min_length=1, max_length=60)
    target_value: str | int | bool
    unit: str | None = None
    raw_mention: str | None = None


class ConstraintExtractionResult(BaseModel):
    constraints: list[ExtractedConstraint] = Field(default_factory=list)
    extraction_method: str = "regex_fallback"
    model_reported: str | None = None
    llm_fallback: bool = False
    failed: bool = False
    attempts: int = 0


def _normalize_field(field: str, unit: str | None) -> str:
    low = field.strip().lower()
    if low in {"width", "width_cm"} or (low == "width" and (unit or "cm").lower() == "cm"):
        return "width_cm"
    if low in {"height", "height_cm"}:
        return "height_cm"
    return low


def extract_constraints_regex(text: str, *, llm_fallback: bool = False, attempts: int = 0) -> ConstraintExtractionResult:
    """Deterministic regex fallback for physical/product constraints."""
    constraints: list[ExtractedConstraint] = []
    lower = (text or "").lower()

    if "width" in lower or "wide" in lower:
        m = re.search(r"(\d+)\s*(cm|mm|in)?\s*wide", lower) or re.search(r"width\s*(?:of|:)?\s*(\d+)\s*(cm|mm|in)?", lower)
        if m:
            constraints.append(ExtractedConstraint(
                field="width_cm",
                target_value=int(m.group(1)),
                unit=m.group(2) or "cm",
                raw_mention=m.group(0),
            ))
        else:
            width_match = re.search(r"\b(\d{2,3})\s*(?:cm|mm|in|inch|inches)?\b", lower)
            if width_match:
                constraints.append(ExtractedConstraint(
                    field="width_cm",
                    target_value=int(width_match.group(1)),
                    unit="cm",
                    raw_mention=width_match.group(0),
                ))
            else:
                constraints.append(ExtractedConstraint(
                    field="width_cm",
                    target_value="unspecified",
                    unit="cm",
                    raw_mention="width",
                ))
    elif m := re.search(r"\b(\d{2,3})\s*(?:cm)?\s*(?:standing\s+)?desk\b", lower):
        constraints.append(ExtractedConstraint(
            field="width_cm",
            target_value=int(m.group(1)),
            unit="cm",
            raw_mention=m.group(0),
        ))
    elif m := re.search(r"\b(?:standing\s+)?desk\s+(\d{2,3})\s*(?:cm)?\b", lower):
        constraints.append(ExtractedConstraint(
            field="width_cm",
            target_value=int(m.group(1)),
            unit="cm",
            raw_mention=m.group(0),
        ))
    elif m := re.search(r"\b(\d{2,3})\s*cm\b", lower):
        constraints.append(ExtractedConstraint(
            field="width_cm",
            target_value=int(m.group(1)),
            unit="cm",
            raw_mention=m.group(0),
        ))

    if "height" in lower or "tall" in lower:
        if m := re.search(r"(\d+)\s*(?:cm|in)?\s*(?:tall|height)", lower):
            constraints.append(ExtractedConstraint(
                field="height_cm",
                target_value=int(m.group(1)),
                unit="cm",
                raw_mention=m.group(0),
            ))

    for color in ("black", "white", "oak", "walnut", "silver", "gray", "grey"):
        if re.search(rf"\b{color}\b", lower):
            constraints.append(ExtractedConstraint(
                field="color",
                target_value=color,
                unit=None,
                raw_mention=color,
            ))
            break

    return ConstraintExtractionResult(
        constraints=constraints,
        extraction_method="regex_fallback",
        llm_fallback=llm_fallback,
        attempts=attempts,
    )


async def _extract_via_llm(
    text: str,
    api_key: str,
    model: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ConstraintExtractionResult:
    base_url = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Extract explicit physical or product constraints (e.g., width_cm, height_cm, color) "
                    "from the buyer instruction. Return JSON only: "
                    '{"constraints":[{"field":"width_cm","target_value":160,"unit":"cm","raw_mention":"160 cm"}]}.'
                ),
            },
            {"role": "user", "content": text},
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": 300,
    }
    attempts = 0
    last_error = "unknown"
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, transport=transport) as client:
        for idx in range(len(BACKOFF_DELAYS) + 1):
            attempts += 1
            try:
                resp = await client.post(
                    f"{base_url}/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                    parsed = json.loads(content)
                    items = []
                    for item in parsed.get("constraints", []):
                        norm = _normalize_field(item["field"], item.get("unit"))
                        items.append(ExtractedConstraint(
                            field=norm,
                            target_value=item["target_value"],
                            unit=item.get("unit"),
                            raw_mention=item.get("raw_mention"),
                        ))
                    return ConstraintExtractionResult(
                        constraints=items,
                        extraction_method="llm_groq",
                        model_reported=data.get("model") or model,
                        llm_fallback=False,
                        attempts=attempts,
                    )
                last_error = f"HTTP {resp.status_code}"
                if resp.status_code != 429 and resp.status_code < 500:
                    break
            except (httpx.HTTPError, ValueError, KeyError, TypeError, ValidationError) as exc:
                last_error = type(exc).__name__
            if idx < len(BACKOFF_DELAYS):
                await asyncio.sleep(BACKOFF_DELAYS[idx])
    raise RuntimeError(f"Constraint extraction failed after {attempts} attempt(s): {last_error}")


async def extract_constraints_async(
    instruction_text: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ConstraintExtractionResult:
    """Extract structured constraints using LLM if configured, falling back safely to regex."""
    key = os.getenv("GROQ_API_KEY", "").strip()
    model = os.getenv("GROQ_MODEL", "").strip() or DEFAULT_MODEL
    if key:
        try:
            return await _extract_via_llm(instruction_text, key, model, transport=transport)
        except Exception as exc:
            logger.warning("Constraint LLM extraction fell back to regex: %s", exc)
            try:
                return extract_constraints_regex(instruction_text, llm_fallback=True)
            except Exception:
                return ConstraintExtractionResult(extraction_method="failed", llm_fallback=True, failed=True)
    try:
        return extract_constraints_regex(instruction_text, llm_fallback=False)
    except Exception:
        return ConstraintExtractionResult(extraction_method="failed", failed=True)


def extract_constraints(instruction_text: str) -> ConstraintExtractionResult:
    """Synchronous regex extraction for transactional policy evaluation (never holds DB locks across HTTP)."""
    try:
        return extract_constraints_regex(instruction_text, llm_fallback=False)
    except Exception:
        return ConstraintExtractionResult(extraction_method="failed", failed=True)


def constraints_to_dict(result: ConstraintExtractionResult) -> tuple[dict[str, Any], bool]:
    merged: dict[str, Any] = {}
    for item in result.constraints:
        merged[item.field] = item.target_value
    return merged, result.failed

