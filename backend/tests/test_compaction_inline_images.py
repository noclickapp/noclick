"""An image in a turn's message (an image URL the agent fetches and sends inline, as a deployment check's
screenshot) costs the model its vision tokens, not its base64 read as text: the compactor's budget must not
refuse the turn for it."""

import base64
import random

import pytest
from agents.run_config import ModelInputData

from coder.openai_agent import compaction

pytestmark = pytest.mark.asyncio

MODEL = "gpt-4o"
# A screenshot's worth of PNG bytes (the check that found this sent ~149KB), as the LLM handler inlines it.
SCREENSHOT = "data:image/png;base64," + base64.b64encode(random.Random(0).randbytes(150_000)).decode()


def _turn():
    return {"role": "user", "content": [
        {"type": "input_text", "text": "The browser check finished: https://example.com/check-home.png"},
        {"type": "input_image", "image_url": SCREENSHOT, "detail": "auto"},
    ]}


class _NoCheckpoint:
    """A conversation with nothing folded yet; nothing here may need folding."""

    def __init__(self, items):
        self.items = items

    async def load(self):
        return {}, self.items

    async def read(self, checkpoint):
        return None

    async def commit(self, **kwargs):
        raise AssertionError("a single short turn has nothing to fold")


async def test_an_inline_image_costs_its_vision_tokens_not_its_base64():
    text_only = compaction.token_count({"role": "user", "content": [_turn()["content"][0]]}, MODEL)
    assert compaction.token_count(_turn(), MODEL) <= text_only + 4096 + 50


async def test_the_summarizer_sees_an_inline_image_as_an_image_never_its_base64_as_text(monkeypatch):
    """Folding a turn that carried an image sends the summarizer the image, not its data URI quoted in the
    transcript: quoted, a screenshot's base64 was read as text, about a token for every 1.5 characters."""
    from agents.models.interface import Model
    from openai.types.responses import Response, ResponseCompletedEvent, ResponseOutputMessage, ResponseOutputText

    from coder.openai_agent import agent as wrapper

    checkpoint = "The browser check of the home page passed: status 200, no console errors."
    answer = f"<description>The check of the home page.</description>\n<checkpoint>\n{checkpoint}\n</checkpoint>"
    seen = []

    class Summarizer(Model):
        async def get_response(self, *args, **kwargs):
            raise AssertionError("Expected streaming")

        async def stream_response(self, system_instructions, input, *args, **kwargs):
            seen.append(input)
            message = ResponseOutputMessage(id="m", type="message", role="assistant", status="completed",
                                            content=[ResponseOutputText(type="output_text", text=answer, annotations=[])])
            response = Response.model_construct(id="r", created_at=0, model="test", object="response",
                                                output=[message], status="completed", usage=None)
            yield ResponseCompletedEvent(type="response.completed", response=response, sequence_number=1)

    monkeypatch.setattr(wrapper, "_build_sdk_model", lambda model, env: Summarizer())
    monkeypatch.setattr(wrapper.Agent, "_build_billing_hooks", lambda self: None)
    summary = await compaction.summarize("", [_turn(), {"role": "assistant", "content": "The check passed."}],
                                         model="test", user_id="u-1", user_email=None, organization_id=None)
    assert summary.content == checkpoint
    [request] = [item for item in seen[0] if item.get("role") == "user"]
    texts = [part["text"] for part in request["content"] if part["type"] == "input_text"]
    images = [part["image_url"] for part in request["content"] if part["type"] == "input_image"]
    assert images == [SCREENSHOT]
    assert "check-home.png" in texts[0] and SCREENSHOT[40:200] not in "".join(texts)


async def test_a_turn_whose_message_carries_an_image_reaches_the_model_with_it():
    raw = [_turn()]
    compactor = compaction.Compactor(_NoCheckpoint(raw), model=MODEL, user_id="u-1")
    data = type("Data", (), {"model_data": ModelInputData(input=raw, instructions="Be brief."),
                             "agent": type("Agent", (), {"tools": []})()})()
    shaped = await compactor(data)
    assert shaped.input == raw


async def test_photos_count_what_a_provider_charges_for_them_at_most():
    """The five photos a turn sees cost a few thousand tokens however large they are, since every provider
    resizes an image before it reads it. Counted at 4,096 each, five were 20k of the 48k budget, and a turn
    carrying a catalog's photos and their links was refused as too large while its real prompt was ~20k."""
    links = "\n\n".join(f"[Image; attachment_id={i:036d}]\nFile: https://assets.example.com/u/account/{i}/image.jpg"
                        for i in range(60))
    photos = [{"type": "input_image", "image_url": SCREENSHOT, "detail": "auto"} for _ in range(5)]
    text_only = compaction.token_count({"role": "user", "content": [{"type": "input_text", "text": links}]}, MODEL)
    with_photos = compaction.token_count({"role": "user", "content": [{"type": "input_text", "text": links}, *photos]},
                                         MODEL)
    # Each image is also its few tokens of JSON in the counted text.
    assert with_photos - text_only <= 5 * (compaction.IMAGE_TOKENS + 50) and compaction.IMAGE_TOKENS <= 1600
