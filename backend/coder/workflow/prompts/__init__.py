"""Prompt loading helpers used by the community builder."""

from pathlib import Path
from typing import Any, Dict, Optional

from jinja2 import Environment, FileSystemLoader

PROMPTS_DIR = Path(__file__).parent


def load_prompt(
    pass_name: str,
    prompt_name: str = "default",
    context: Optional[Dict[str, Any]] = None,
) -> str:
    """Load and render a prompt template from this package."""
    env = Environment(loader=FileSystemLoader(PROMPTS_DIR))
    template = env.get_template(f"{pass_name}/{prompt_name}.j2")
    return template.render(**(context or {}))


