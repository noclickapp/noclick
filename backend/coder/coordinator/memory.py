"""Progressive memory disclosure for every coordinator transport.
Only complete, model-authored retrieval headers enter the prompt; full memory
bodies and older messages remain behind explicit retrieval tools.
"""

import asyncio
import json

from repositories.coordinator_memories import CoordinatorMemoryRepo
from utils.prompts import PromptPack

CATALOG_TOKEN_BUDGET = 2000
PROMPTS = PromptPack("coordinator")


def render_catalog(headers: list[dict], *, has_more: bool, model: str, budget: int = CATALOG_TOKEN_BUDGET) -> str:
    from litellm import token_counter

    if not headers:
        return ""
    prefix = "\n\n" + PROMPTS.MEMORY_CATALOG_HEADER + "\n"
    suffix = "\n" + PROMPTS.MEMORY_CATALOG_MORE
    lines = []
    for row in headers:
        header = json.dumps({
            "id": row["id"], "name": row["name"], "description": row["description"],
            "metadata": {"node_type": "memory", "type": row["memory_type"],
                         "originSessionId": row["origin_conversation_id"]},
        }, ensure_ascii=False, separators=(",", ":"))
        candidate = prefix + "\n".join([*lines, header]) + suffix
        if token_counter(model=model, text=candidate) > budget:
            has_more = True
            continue
        lines.append(header)
    return prefix + "\n".join(lines) + (suffix if has_more else "")


async def memory_context(pool, user_id: str, *, model: str) -> str:
    page = await CoordinatorMemoryRepo(pool).list_headers(user_id, limit=100)
    return await asyncio.to_thread(render_catalog, page["memories"], has_more=page["has_more"], model=model)
