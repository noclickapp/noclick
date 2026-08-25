"""Chat-message attachments (config.message_attachments).

Covers the pure helpers in nodes/agent/attachments.py (normalize → persist
split → message block), the hidden config field on BaseAgentFields, and the
SDK wrapper's multimodal input builder (Agent._build_user_input) — the seam
that previously flattened image content items to text, dropping them.
"""

import pytest

from nodes.agent.attachments import (
    ATTACHMENTS_BLOCK_HEADER,
    apply_media_attachment_images,
    format_attachments_block,
    normalize_message_attachments,
    split_attachment_media,
)


IMG = {
    "resource_id": "res-img",
    "url": "https://assets.example.test/u/wf/res-img/shot.png",
    "name": "shot.png",
    "mime_type": "image/png",
    "size_bytes": 2048,
}
PDF = {
    "resource_id": "res-pdf",
    "url": "https://assets.example.test/u/wf/res-pdf/report.pdf",
    "name": "report.pdf",
    "mime_type": "application/pdf",
    "size_bytes": 5 * 1024 * 1024,
}


class TestNormalizeMessageAttachments:
    def test_valid_entries_pass_through(self):
        out = normalize_message_attachments([IMG, PDF])
        assert [a["url"] for a in out] == [IMG["url"], PDF["url"]]
        assert out[0]["mime_type"] == "image/png"
        assert out[1]["size_bytes"] == PDF["size_bytes"]

    @pytest.mark.parametrize(
        "raw", [None, "not-a-list", {}, 42, [{"name": "no-url.txt"}], ["str-entry"]]
    )
    def test_invalid_shapes_yield_empty_or_skip(self, raw):
        assert normalize_message_attachments(raw) == []

    def test_non_http_url_dropped(self):
        assert (
            normalize_message_attachments(
                [{"url": "javascript:alert(1)", "name": "x"}]
            )
            == []
        )

    def test_name_falls_back_to_url_tail(self):
        out = normalize_message_attachments(
            [{"url": "https://assets.example.test/u/wf/r/data.csv"}]
        )
        assert out[0]["name"] == "data.csv"

    def test_mime_defaults_to_octet_stream_and_bad_size_dropped(self):
        out = normalize_message_attachments(
            [{"url": "https://x.example/f", "size_bytes": "huge"}]
        )
        assert out[0]["mime_type"] == "application/octet-stream"
        assert out[0]["size_bytes"] is None


class TestSplitAttachmentMedia:
    def test_images_and_files_split_by_mime(self):
        image_urls, files = split_attachment_media(
            normalize_message_attachments([IMG, PDF])
        )
        assert image_urls == [IMG["url"]]
        assert files == [
            {
                "name": "report.pdf",
                "url": PDF["url"],
                "mime_type": "application/pdf",
            }
        ]

    def test_empty(self):
        assert split_attachment_media([]) == ([], [])


class TestFormatAttachmentsBlock:
    def test_block_carries_name_mime_size_and_url(self):
        block = format_attachments_block(normalize_message_attachments([IMG, PDF]))
        assert block.startswith(ATTACHMENTS_BLOCK_HEADER)
        assert "- shot.png (image/png, 2.0 KB): " + IMG["url"] in block
        assert "- report.pdf (application/pdf, 5.0 MB): " + PDF["url"] in block
        # The hint tells CLI harnesses how to reach non-image contents.
        assert "curl" in block

    def test_sizeless_entry_omits_size(self):
        block = format_attachments_block(
            normalize_message_attachments([{"url": "https://x.example/a.txt"}])
        )
        assert "- a.txt (application/octet-stream): https://x.example/a.txt" in block


class TestConfigField:
    def test_base_agent_fields_accepts_and_defaults_message_attachments(self):
        from nodes.agent.config.base import BaseAgentFields

        assert BaseAgentFields(message="hi").message_attachments is None
        cfg = BaseAgentFields(message="hi", message_attachments=[IMG])
        assert cfg.message_attachments == [IMG]

    def test_schema_hides_the_field_from_the_config_form(self):
        from nodes.agent.config.base import BaseAgentFields

        schema = BaseAgentFields.model_json_schema()
        assert schema["properties"]["message_attachments"]["ui:hidden"] is True


class TestBuildUserInput:
    """Agent._build_user_input — text-only turns stay plain strings (compact
    history rows); image-bearing turns become the SDK multi-content form."""

    @staticmethod
    def _build(items):
        from coder.openai_agent.agent import Agent

        return Agent._build_user_input({"content_items": items})

    def test_text_only_returns_plain_string(self):
        from wss.sender.schema import ContentItem

        out = self._build(
            [
                ContentItem(type="text", text="hello"),
                ContentItem(type="text", text="world"),
            ]
        )
        assert out == "hello\nworld"

    def test_empty_items_return_empty_string(self):
        assert self._build([]) == ""

    def test_text_plus_image_returns_multi_content(self):
        from wss.sender.schema import ContentItem, ImageUrl

        out = self._build(
            [
                ContentItem(type="text", text="what is this?"),
                ContentItem(
                    type="image_url",
                    image_url=ImageUrl(url="data:image/png;base64,AAAA", detail="auto"),
                ),
            ]
        )
        assert out == [
            {"type": "input_text", "text": "what is this?"},
            {
                "type": "input_image",
                "image_url": "data:image/png;base64,AAAA",
                "detail": "auto",
            },
        ]

    def test_image_only_omits_the_empty_text_part(self):
        from wss.sender.schema import ContentItem

        out = self._build(
            [ContentItem(type="image_url", image_url="https://x.example/i.png")]
        )
        assert out == [
            {
                "type": "input_image",
                "image_url": "https://x.example/i.png",
                "detail": "auto",
            }
        ]

    def test_dict_items_accepted_like_content_items(self):
        out = self._build(
            [
                {"type": "text", "text": "hi"},
                {"type": "image_url", "image_url": {"url": "https://x.example/i.png"}},
            ]
        )
        assert out[0] == {"type": "input_text", "text": "hi"}
        assert out[1]["image_url"] == "https://x.example/i.png"

    def test_imageless_image_item_is_skipped(self):
        out = self._build([{"type": "image_url"}, {"type": "text", "text": "hi"}])
        assert out == "hi"


class TestMediaAttachmentInputs:
    """apply_media_attachment_images — attached images ride the media
    handlers' structured input seams, never the generation prompt."""

    @staticmethod
    def _attachments():
        return normalize_message_attachments([IMG, PDF])

    def test_image_model_merges_into_gemini_reference_urls(self):
        import json
        from types import SimpleNamespace

        config = SimpleNamespace(
            model_type="image",
            gemini_reference_image_url="https://x.example/existing.png",
        )
        applied = apply_media_attachment_images(config, self._attachments())
        assert applied == 1
        assert json.loads(config.gemini_reference_image_url) == [
            IMG["url"],
            "https://x.example/existing.png",
        ]

    def test_video_model_fills_empty_veo_image_url(self):
        from types import SimpleNamespace

        config = SimpleNamespace(model_type="video", veo_image_url="")
        assert apply_media_attachment_images(config, self._attachments()) == 1
        assert config.veo_image_url == IMG["url"]

    def test_user_set_frame_is_never_overridden(self):
        from types import SimpleNamespace

        config = SimpleNamespace(
            model_type="kling", kling_image_url="https://x.example/frame.png"
        )
        assert apply_media_attachment_images(config, self._attachments()) == 0
        assert config.kling_image_url == "https://x.example/frame.png"

    def test_kling_model_fills_empty_kling_image_url(self):
        from types import SimpleNamespace

        config = SimpleNamespace(model_type="kling", kling_image_url="")
        assert apply_media_attachment_images(config, self._attachments()) == 1
        assert config.kling_image_url == IMG["url"]

    def test_non_image_attachments_do_nothing(self):
        from types import SimpleNamespace

        config = SimpleNamespace(model_type="video", veo_image_url="")
        applied = apply_media_attachment_images(
            config, normalize_message_attachments([PDF])
        )
        assert applied == 0
        assert config.veo_image_url == ""


@pytest.mark.asyncio
class TestRunnerInputShapes:
    """What Agent.__call__ actually hands Runner.run_streamed — the wire-shape
    guarantee that images reach the SDK (they were dropped pre-fix)."""

    @staticmethod
    def _multimodal_message():
        return {
            "content_items": [
                {"type": "text", "text": "what is in this?"},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,AAAA"},
                },
            ]
        }

    async def _run(self, agent, message):
        from unittest.mock import patch

        from tests.test_agent_llm_retry import FakeResult

        with patch(
            "coder.openai_agent.agent.Runner.run_streamed",
            side_effect=[FakeResult(final_output="ok")],
        ) as run:
            await agent(message)
        assert run.call_count == 1
        return run.call_args.args[1]

    async def test_session_path_text_only_stays_plain_string(self):
        from unittest.mock import MagicMock

        from tests.test_agent_llm_retry import _make_agent

        agent = _make_agent([])
        agent._session = MagicMock()
        input_list = await self._run(
            agent, {"content_items": [{"type": "text", "text": "hi"}]}
        )
        assert input_list == "hi"

    async def test_session_path_multimodal_sends_content_parts(self):
        from unittest.mock import MagicMock

        from tests.test_agent_llm_retry import _make_agent

        agent = _make_agent([])
        agent._session = MagicMock()
        input_list = await self._run(agent, self._multimodal_message())
        assert input_list == [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "what is in this?"},
                    {
                        "type": "input_image",
                        "image_url": "data:image/png;base64,AAAA",
                        "detail": "auto",
                    },
                ],
            }
        ]

    async def test_in_memory_history_prepends_and_keeps_parts(self):
        from tests.test_agent_llm_retry import _make_agent

        agent = _make_agent([])
        agent._history = [{"role": "assistant", "content": "earlier turn"}]
        input_list = await self._run(agent, self._multimodal_message())
        assert input_list[0] == {"role": "assistant", "content": "earlier turn"}
        assert input_list[1]["role"] == "user"
        assert input_list[1]["content"][1]["type"] == "input_image"
