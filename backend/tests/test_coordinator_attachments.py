"""Real file persistence/extraction and SDK vision input; only external I/O is stubbed."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from coder.coordinator import attachments, compaction
from coder.coordinator.tools import CoordinatorTools
from tests.test_builder_requests import USER, builder_request_db  # noqa: F401
from tests.mocks.pdf_fixtures import blank_pdf, text_pdf
from utils.content_extraction import BillingContext

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def files(builder_request_db, monkeypatch):
    pool = builder_request_db[0]
    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: pool)
    upload = AsyncMock()
    monkeypatch.setattr("utils.resource_store.upload_bytes_to_r2_async", upload)
    monkeypatch.setattr("utils.resource_store.get_public_download_url", lambda key: "https://assets.example/" + key)
    monkeypatch.setattr("utils.r2_cloudflare.get_public_download_url", lambda key: "https://assets.example/" + key)
    yield pool, upload
    await pool.execute("DELETE FROM workflow_resources WHERE owner_id=$1::uuid AND workflow_id IS NULL", USER)


async def prepare(data, **kw):
    args = dict(kind="document", mime_type="text/plain", filename="notes.txt", caption="Please read this",
                billing=BillingContext(user_id=USER))
    return await attachments.prepare_attachment(data, **{**args, **kw})


async def test_pdf_and_long_text_are_stored_and_paged_with_owner_scope(files):
    pool, upload = files
    text, images = await prepare(text_pdf(), mime_type="application/pdf", filename="invoice.pdf")
    assert "$10" in text and not images
    long_text = "A" * 8000 + "The answer after the first page is 42."
    text, _ = await prepare(long_text.encode(), filename="../../notes[bad].txt")
    assert "offset=8000" in text and "is 42" not in text
    row = await pool.fetchrow("SELECT * FROM workflow_resources WHERE name='notes_bad_.txt'")
    assert row and str(row["owner_id"]) == USER and row["workflow_id"] is None
    assert upload.await_args.kwargs["body"] == long_text.encode()
    tool = CoordinatorTools(pool=pool, sio=None, user_id=USER, organization_id=None,
                            conversation_id=f"coordinator:{USER}")
    page = await tool.execute("read_attachment", {"attachment_id": str(row["id"]), "offset": 8000})
    assert page["text"].endswith("is 42.") and page["next_offset"] is None
    assert page["download_url"] == "https://assets.example/" + row["storage_ref"]
    with pytest.raises(ValueError, match="not found"):
        await attachments.read_attachment(pool, "00000000-0000-0000-0000-000000000003", str(row["id"]))
    with pytest.raises(ValueError, match="nonnegative"):
        await attachments.read_attachment(pool, USER, str(row["id"]), -1)


async def test_a_file_uploads_while_it_is_read(files, monkeypatch):
    """A voice note's turn waits on its upload and its transcript: one goes while the other is made."""
    import asyncio

    pool, upload = files
    uploading = asyncio.Event()

    async def store(**kwargs):
        uploading.set()

    async def transcribe(ref, data, billing):
        await asyncio.wait_for(uploading.wait(), timeout=2)  # the upload started before the reading ended
        return {"extracted_text": "What's my balance?", "extraction_method": "ai_transcription",
                "extraction_error": ""}

    upload.side_effect = store
    monkeypatch.setattr(attachments, "_read", transcribe)
    text, _ = await prepare(b"OggS voice", kind="audio", mime_type="audio/ogg", filename="note.ogg", voice=True,
                            caption="")
    assert text.endswith("What's my balance?")
    row = await pool.fetchrow("SELECT * FROM workflow_resources WHERE name = 'note.ogg'")
    assert row["metadata"]["extracted_text"] == "What's my balance?" and row["size_bytes"] == len(b"OggS voice")
    assert upload.await_args.kwargs["key"] == row["storage_ref"]


async def test_scanned_pdf_uses_billed_ocr_and_paging_does_not_repeat_it(files, monkeypatch):
    pool, _ = files
    from billing.usage_tracker import usage_tracker

    gate, track = AsyncMock(), AsyncMock()
    # The model's answer carries its cost (OpenRouter's usage accounting), which the charge records.
    model = AsyncMock(return_value=SimpleNamespace(usage=SimpleNamespace(cost=0.003, total_tokens=900),
                                                   choices=[SimpleNamespace(message=SimpleNamespace(content="Scanned receipt: $42"))]))
    monkeypatch.setattr(usage_tracker, "enforce_credit_gate", gate)
    monkeypatch.setattr(usage_tracker, "track_usage_event", track)
    monkeypatch.setattr("litellm.acompletion", model)
    text, _ = await prepare(blank_pdf(), mime_type="application/pdf", filename="scan.pdf")
    assert "Scanned receipt: $42" in text
    gate.assert_awaited_once()
    assert track.await_args.args[0].usage_subtype == "extraction/ai_ocr"
    row = await pool.fetchrow("SELECT id FROM workflow_resources WHERE name='scan.pdf'")
    assert (await attachments.read_attachment(pool, USER, str(row["id"])))["text"] == "Scanned receipt: $42"
    model.assert_awaited_once()


async def test_unsupported_document_is_retained_with_caption_and_honest_error(files):
    text, images = await prepare(b"zip", mime_type="application/zip", filename="archive.zip")
    assert "Please read this" in text and "could not be read" in text and not images
    assert "File: https://assets.example/" in text


async def test_image_uses_url_vision_input_without_base64_in_history(files):
    from coder.openai_agent import Agent
    from coder.openai_agent.compaction import IMAGE_TOKENS

    text, images = await prepare(b"image", kind="image", mime_type="image/jpeg", filename="photo.jpg")
    assert "Please read this" in text
    from wss.sender.schema import ContentItem

    content = Agent._build_user_input({"content_items": [ContentItem(type="text", text=text), *images]})
    assert content[1]["type"] == "input_image" and content[1]["image_url"].startswith("https://assets.example/")
    assert "base64" not in str(content)
    assert compaction.token_count([{"role": "user", "content": content}], "gpt-4o") >= IMAGE_TOKENS


async def test_checkpoint_summarizer_receives_native_images(monkeypatch):
    from agents.models.interface import Model
    from openai.types.responses import Response, ResponseCompletedEvent, ResponseOutputMessage, ResponseOutputText
    from coder.openai_agent import Agent
    from coder.openai_agent.compaction import IMAGE_TOKENS

    captured = []
    class VisionModel(Model):
        async def get_response(self, *a, **kw):
            raise AssertionError("Expected streaming")

        async def stream_response(self, system_instructions, input, *a, **kw):
            captured.extend(input)
            text = ("<description>Photo of a receipt with an exact total.</description>\n<checkpoint>The receipt in "
                    "photo.jpg shows a total of $42. Keep that fact for the pending report.</checkpoint>")
            output = [ResponseOutputMessage(id="m1", type="message", role="assistant", status="completed",
                        content=[ResponseOutputText(type="output_text", text=text, annotations=[])])]
            yield ResponseCompletedEvent(type="response.completed", sequence_number=0,
                response=Response.model_construct(id="r1", created_at=0, model="test", object="response", output=output,
                                                   status="completed", usage=None))

    original = Agent.create
    async def create(**kw):
        agent = await original(**kw)
        agent._sdk_agent.model = VisionModel()
        agent._billing_hooks = None
        return agent
    monkeypatch.setattr(Agent, "create", create)
    items = [{"role": "user", "content": [{"type": "input_text", "text": "What is the total?"},
                                         {"type": "input_image", "image_url": "https://assets.example/photo.jpg"}]}]
    result = await compaction.summarize("", items, model="gpt-4o", user_id=USER, user_email=None, organization_id=None)
    assert "$42" in result.content
    assert list(compaction.image_inputs(captured))[0]["image_url"] == "https://assets.example/photo.jpg"


async def test_a_file_sent_without_its_extension_is_kept_under_one(files):
    pool, _ = files
    await prepare(b"hello there", filename="notes")
    row = await pool.fetchrow("SELECT name, storage_ref FROM workflow_resources WHERE owner_id = $1::uuid "
                              "ORDER BY created_at DESC LIMIT 1", USER)
    assert row["name"] == "notes.txt" and row["storage_ref"].endswith("/notes.txt")
    # A name that names its type keeps it; one that names nothing takes the type's.
    assert attachments.classify("document", "application/pdf", "Q3 plan.pdf").name == "Q3 plan.pdf"
    assert attachments.classify("document", "application/pdf", "Q3 plan v1.2").name == "Q3 plan v1.2.pdf"
