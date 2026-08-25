"""Mock-based tests for the OpenClaw CLI sandbox handler."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestOpenClawConfig:
    def _make_config(self, **kwargs):
        from nodes.agent.config.openclaw import OpenClawConfig

        defaults = {
            "message": "Summarize the repository status",
        }
        defaults.update(kwargs)
        return OpenClawConfig(**defaults)

    def test_defaults(self):
        cfg = self._make_config()
        assert cfg.model == "openclaw"
        assert cfg.model_type == "openclaw"
        # Default comes from the default_model pin in _cli_models.json —
        # the one ground truth for all harness defaults.
        from nodes.agent.config._cli_models_loader import harness_default_model
        assert cfg.openclaw_model == harness_default_model("openclaw")
        assert cfg.timeout_seconds == 600

    def test_timeout_bounds(self):
        cfg = self._make_config(timeout_seconds=120)
        assert cfg.timeout_seconds == 120

    def test_timeout_negative_rejected(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            self._make_config(timeout_seconds=-1)


class TestModelTypeInference:
    def test_openclaw_inferred(self):
        from nodes.agent.config.base import infer_model_type

        data = {"model": "openclaw", "message": "test"}
        result = infer_model_type(data)
        assert result["model_type"] == "openclaw"










