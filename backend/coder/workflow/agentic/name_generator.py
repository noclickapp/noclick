"""
Cheap, non-blocking naming LLM call used when the user kicks off a brand-new
workflow from WorkflowCreator. Fires in the background alongside the main
brain loop so the placeholder name (a slice of the user's prompt) gets
replaced by a short, descriptive title within a few seconds.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional, Tuple

import litellm

logger = logging.getLogger(__name__)

_NAMING_SYSTEM_PROMPT = """You generate short, descriptive titles and one-line summaries for workflow automations.

Given a user's build request, respond with ONLY a single JSON object on one line:
{"name": "...", "description": "..."}

Rules:
- "name" is 3-6 words, Title Case, no quotes, no trailing punctuation, ≤60 characters.
- "description" is one sentence (≤140 chars) describing what the workflow does.
- Do not include any other text, code fences, or explanations. JSON only."""


async def generate_workflow_name(
    prompt: str,
    model: str = "openrouter/openai/gpt-oss-120b",
    timeout: float = 25.0,
    max_attempts: int = 2,
) -> Optional[Tuple[str, str]]:
    """
    Return (name, description) for the given build prompt, or None on failure.

    This runs as a fire-and-forget background task; callers should not treat
    a None return as an error worth surfacing to the user — the placeholder
    name (prompt slice) remains in place.

    Retries once on timeout since openrouter cold-starts occasionally blow past
    the budget even though typical latency is ~2s.
    """
    content = ""
    last_error: Optional[Exception] = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = await litellm.acompletion(
                model=model,
                messages=[
                    {"role": "system", "content": _NAMING_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt.strip()},
                ],
                temperature=0.3,
                max_tokens=120,
                timeout=timeout,
            )
            content = response.choices[0].message.content or ""
            break
        except Exception as e:
            last_error = e
            logger.warning(f"[NameGen] LLM call attempt {attempt}/{max_attempts} failed: {e}")
    if not content:
        logger.warning(f"[NameGen] Giving up after {max_attempts} attempts: {last_error}")
        return None

    # The model is instructed to return raw JSON; be defensive anyway.
    cleaned = content.strip()
    # Strip code fences if the model ignored instructions.
    match = re.search(r"\{[\s\S]*\}", cleaned)
    if not match:
        logger.warning(f"[NameGen] No JSON object in response: {cleaned[:120]}")
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as e:
        logger.warning(f"[NameGen] JSON parse failed: {e} — raw: {cleaned[:120]}")
        return None

    name = (data.get("name") or "").strip()
    description = (data.get("description") or "").strip()
    if not name:
        return None

    # Hard cap in case the model ignores the length rules.
    if len(name) > 80:
        name = name[:77].rstrip() + "…"
    if len(description) > 200:
        description = description[:197].rstrip() + "…"

    return name, description
