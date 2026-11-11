"""Request and polling tests against the published obono 1.4.0.0 shapes.

Synthetic values below exercise fields defined in api.yml; they are not live
account recordings or provider-authored examples.
"""
import json
from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from pydantic import ValidationError
from nodes.core.binary_output import BinaryOutput, resolve_binary_outputs

from nodes.obono_node import (
    CONFIG_MODELS, ObonoNode, ObonoNodeConfig, ObonoOnNewReceiptConfig, ObonoTokenCredential,
)


ROOT = "https://app.obono.at/api/v1"
REGISTER = "00000000-0000-4000-8000-000000000001"
RECEIPT = "00000000-0000-4000-8000-000000000002"


def node(operation, **values):
    model = ObonoOnNewReceiptConfig if operation == "on_new_receipt" else CONFIG_MODELS[operation]
    if operation == "on_new_receipt":
        values.setdefault("register_uuid", REGISTER)
    return ObonoNode(node_id="obono-test", node_type="automation-obono", node_data={},
        config=ObonoNodeConfig(config=model(**values), credentials=ObonoTokenCredential(
            access_token="test-access-token", register_uuid=REGISTER)))


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,path,query,media", [
    ("get_register", f"/registrierkassen/{REGISTER}", {}, "application/json"),
    ("list_receipts", f"/registrierkassen/{REGISTER}/belege", {"format": "beleg", "limit": 10, "offset": 20, "order": "desc", "after": "2026-01-01", "before": "2026-02-01", "gte": 10, "lte": 30}, "application/json"),
    ("get_receipt", f"/registrierkassen/{REGISTER}/belege/{RECEIPT}", {}, "application/json"),
    ("list_monthly_receipts", f"/registrierkassen/{REGISTER}/monatsbelege", {"year": 2026, "month": 1}, "application/json"),
    ("get_dep", f"/registrierkassen/{REGISTER}/dep", {}, "application/json"),
    ("export_receipt_pdf", f"/export/pdf/belege/{RECEIPT}", {}, "application/pdf"),
    ("export_receipt_qr", f"/export/qr/belege/{RECEIPT}", {}, "image/png"),
    ("export_receipt_html", f"/export/html/belege/{RECEIPT}", {}, "text/html"),
    ("export_thermal_print", f"/export/thermal-print/belege/{RECEIPT}", {"qr": False, "width": 42, "dialect": "star", "encoding": "base64"}, "application/octet-stream"),
    ("export_gobd", f"/export/gobd/registrierkassen/{REGISTER}", {"after": "2026-01-01"}, "application/zip"),
    ("export_excel", f"/export/xls/registrierkassen/{REGISTER}/belege", {"before": "2026-02-01"}, "application/vnd.ms-excel"),
    ("export_csv", f"/export/csv/registrierkassen/{REGISTER}/belege", {"posten": False}, "text/csv"),
    ("export_dep7", f"/export/dep7/registrierkassen/{REGISTER}/belege", {}, "application/json"),
    ("export_dep131", f"/export/dep131/registrierkassen/{REGISTER}/belege", {}, "text/csv"),
])
async def test_reads_and_exports(operation, path, query, media):
    values = dict(query)
    if "/belege/" in path:
        values["receipt_uuid"] = RECEIPT
    n = node(operation, **values)
    with respx.mock as router:
        response = httpx.Response(200, json={"_uuid": RECEIPT}) if media == "application/json" else httpx.Response(200, content=b"export-data")
        route = router.get(ROOT + path).mock(return_value=response)
        result = await n.execute({})
    req = route.calls[0].request
    assert dict(req.url.params) == {k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in query.items()}
    assert req.headers["Accept"] == media
    if path.startswith("/export/") and "/belege/" in path:
        assert "Authorization" not in req.headers
    else:
        assert req.headers["Authorization"] == "Bearer test-access-token"
    if media == "application/json":
        assert result["data"]["_uuid"] == RECEIPT
    elif media.startswith("text/"):
        assert result["data"]["content"] == "export-data"
    else:
        marker = result["data"]
        assert isinstance(marker, BinaryOutput)
        assert marker.data == b"export-data"
        assert marker.content_type == media
        extension = {"application/pdf": "pdf", "image/png": "png",
            "application/zip": "zip", "application/vnd.ms-excel": "xls"}.get(media, "bin")
        assert marker.filename == f"obono-{RECEIPT if '/belege/' in path else REGISTER}.{extension}"


@pytest.mark.asyncio
async def test_download_resolves_to_a_usable_file_reference(monkeypatch):
    store = AsyncMock(return_value={"download_url": "https://files.example/receipt.pdf",
        "mime_type": "application/pdf", "name": f"obono-{RECEIPT}.pdf", "size_bytes": 14})
    monkeypatch.setattr("nodes.core.binary_output.create_resource_from_bytes", store)
    with respx.mock as router:
        router.get(ROOT + f"/export/pdf/belege/{RECEIPT}").mock(
            return_value=httpx.Response(200, content=b"%PDF-receipt%\n"))
        output = await node("export_receipt_pdf", receipt_uuid=RECEIPT).execute({})
    resolved = await resolve_binary_outputs(output, user_id="user", workflow_id="workflow")
    assert resolved["data"] == {"url": "https://files.example/receipt.pdf",
        "mime_type": "application/pdf", "name": f"obono-{RECEIPT}.pdf", "size_bytes": 14}
    assert store.await_args.kwargs["body"] == b"%PDF-receipt%\n"
    assert store.await_args.kwargs["content_type"] == "application/pdf"
    assert store.await_args.kwargs["filename"] == f"obono-{RECEIPT}.pdf"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,method,path,config,body", [
    ("create_receipt", "PUT", f"/registrierkassen/{REGISTER}/belege/{RECEIPT}", {
        "receipt_uuid": RECEIPT, "receipt_data": {"Posten": [{"Bezeichnung": "Coffee", "Satz": "NORMAL", "Menge": 1, "NettoBetrag": 250, "BruttoBetrag": 300}], "Zahlungen": [{"Bezeichnung": "Cash", "Betrag": 300}], "Training": True}},
        {"Posten": [{"Bezeichnung": "Coffee", "Satz": "NORMAL", "Menge": 1, "NettoBetrag": 250, "BruttoBetrag": 300}], "Zahlungen": [{"Bezeichnung": "Cash", "Betrag": 300}], "Training": True}),
    ("create_closing_receipt", "POST", f"/registrierkassen/{REGISTER}/abschluss", {
        "closing_data": {"Abschluss-Beginn-Datum-Uhrzeit": "2026-01-01T00:00:00Z", "Abschluss-Ende-Datum-Uhrzeit": "2026-02-01T00:00:00Z"}},
        {"Abschluss-Beginn-Datum-Uhrzeit": "2026-01-01T00:00:00Z", "Abschluss-Ende-Datum-Uhrzeit": "2026-02-01T00:00:00Z"}),
])
async def test_writes_preserve_provider_fields_and_empty_201(operation, method, path, config, body):
    with respx.mock as router:
        route = router.request(method, ROOT + path).mock(return_value=httpx.Response(201, headers={"Location": "/api/v1/belege/" + RECEIPT}))
        result = await node(operation, **config).execute({})
    assert json.loads(route.calls[0].request.content) == body
    assert result["data"] == {"http_status": 201, "location": "/api/v1/belege/" + RECEIPT}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 409, 429, 500, 302])
async def test_errors_are_not_retried_or_followed(status):
    with respx.mock as router:
        route = router.get(ROOT + f"/registrierkassen/{REGISTER}").mock(return_value=httpx.Response(status, text="Provider says no test-access-token"))
        with pytest.raises(ValueError, match=f"obono API {status}") as error:
            await node("get_register").execute({})
    assert "test-access-token" not in str(error.value)
    assert route.call_count == 1


def test_manual_credentials_and_body_validation():
    credential = ObonoTokenCredential(access_token=" Bearer test-token ", register_uuid=REGISTER)
    assert credential.credential_type == "obono_token"
    assert credential.access_token == "test-token"
    with pytest.raises(ValidationError):
        ObonoTokenCredential(access_token="token", register_uuid="https://example.com")
    with pytest.raises(ValidationError):
        node("create_receipt", receipt_uuid=RECEIPT, receipt_data={"Posten": [{"Bezeichnung": "Coffee"}]})
    with pytest.raises(ValidationError):
        node("create_closing_receipt", closing_data={})
    with pytest.raises(ValidationError):
        node("create_receipt", receipt_uuid=RECEIPT, receipt_data={"Storno-Beleg-UUID": "invalid"})


@pytest.mark.asyncio
async def test_poll_baselines_then_emits_new_receipts(monkeypatch):
    # These fields are defined in Beleg and SignierteBelegdaten in api.yml.
    first = {"_uuid": RECEIPT, "Belegdaten": {"Belegnummer": "1", "Kunde": "Ada", "Betrag-Brutto": 300, "Beleg-Datum-Uhrzeit": "2026-01-01T12:00:00Z"}}
    second = {**first, "_uuid": "00000000-0000-4000-8000-000000000003"}
    n = node("on_new_receipt", after="2026-01-01")
    state = {}
    async def update(mutator, **kwargs):
        changed, output = mutator(state)
        if changed is not None:
            state.update(changed)
        return output
    monkeypatch.setattr(n, "_update_node_state", update)
    with respx.mock as router:
        route = router.get(ROOT + f"/registrierkassen/{REGISTER}/belege").mock(side_effect=[
            httpx.Response(200, json={"Belege": [first]}),
            httpx.Response(200, json={"Belege": [first, second]}),
            httpx.Response(200, json={"Belege": [first, second]}),
        ])
        baseline = await n.execute({})
        assert baseline["new_receipt_count"] == 0
        fresh = await n.execute({})
        assert fresh["receipts"] == [second]
        assert second["_uuid"] in n.resolve_agent_event(fresh)["text"]
        assert "Ada" in n.resolve_agent_event(fresh)["text"]
        assert (await n.execute({}))["new_receipt_count"] == 0
    assert dict(route.calls[0].request.url.params) == {"format": "beleg", "order": "asc", "limit": "100", "offset": "0", "after": "2026-01-01"}


@pytest.mark.asyncio
async def test_poll_reads_all_pages_before_recording_seen(monkeypatch):
    n = node("on_new_receipt")
    filter_unseen = AsyncMock(side_effect=lambda rows, key: rows)
    monkeypatch.setattr(n, "_filter_unseen", filter_unseen)
    page = [{"_uuid": str(i)} for i in range(100)]
    with respx.mock as router:
        route = router.get(ROOT + f"/registrierkassen/{REGISTER}/belege").mock(side_effect=[
            httpx.Response(200, json={"Belege": page}), httpx.Response(200, json={"Belege": [{"_uuid": "last"}]})])
        assert (await n.execute({}))["new_receipt_count"] == 101
    assert route.calls[1].request.url.params["offset"] == "100"
    assert len(filter_unseen.call_args.args[0]) == 101


@pytest.mark.asyncio
async def test_malformed_poll_does_not_advance_state(monkeypatch):
    n = node("on_new_receipt")
    seen = AsyncMock()
    monkeypatch.setattr(n, "_filter_unseen", seen)
    with respx.mock as router:
        router.get(ROOT + f"/registrierkassen/{REGISTER}/belege").mock(return_value=httpx.Response(200, json={"Belege": [{}]}))
        with pytest.raises(ValueError, match="UUID"):
            await n.execute({})
    seen.assert_not_called()


def test_poll_scope_tracks_register_and_filter():
    from nodes.core.poll_trigger import poll_scope
    config = {"operation": "on_new_receipt", "register_uuid": REGISTER}
    original = poll_scope(ObonoNode, config)
    assert original
    assert original == poll_scope(ObonoNode, {**config, "label": "Renamed node"})
    assert original != poll_scope(ObonoNode, {**config, "register_uuid": RECEIPT})
    assert original != poll_scope(ObonoNode, {**config, "after": "2026-01-01"})
