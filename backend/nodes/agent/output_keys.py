"""The top-level keys an agent step's output has (``WorkflowNode.declared_output_keys``), so the builder judges a
``$('agent').key`` read before the agent has ever run. A first build of an email digest read the agent's reply as
``$('agent').body``; nothing had run, so nothing said the agent answers in ``response``, and every scheduled run
failed on an empty email body.

An agent that runs in this process (a model, an image or a video model) returns one envelope whatever it was asked;
a coding harness's reply carries what its harness reports, which only a run shows."""

from typing import Any, Dict, List, Optional

IN_PROCESS_MODEL_TYPES = frozenset({"llm", "image", "video", "kling"})

# Every key the in-process handlers (nodes/agent/handlers/) and AgentNode.execute put on the output: the reply is
# `response` (parsed JSON when the model answered in JSON), and a wake-up with nothing to relay is `skipped`.
OUTPUT_KEYS = (
    "type", "status", "response", "model", "temperature", "error", "ended_by", "handed_on",
    "images", "image_url", "videos", "video_url", "conversation_key", "message", "skipped",
)


def runs_in_process(config: Dict[str, Any]) -> bool:
    """Whether the agent's model runs in this process, not in a coding harness's sandbox."""
    from nodes.agent.config.base import infer_model_type

    probe = {"model": (config or {}).get("model") or ""}
    if (config or {}).get("model_type"):
        probe["model_type"] = config["model_type"]
    return infer_model_type(probe).get("model_type", "llm") in IN_PROCESS_MODEL_TYPES


def agent_output_keys(config: Dict[str, Any]) -> Optional[List[str]]:
    """The agent's output keys for its config as saved, or None for a coding harness."""
    return list(OUTPUT_KEYS) if runs_in_process(config) else None
