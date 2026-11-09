"""TomTom request placement, binary output, errors and documented route defects."""
from unittest.mock import AsyncMock
import httpx
import pytest
from pydantic import ValidationError
from nodes.core.binary_output import BinaryOutput
from nodes.tomtom_node import TomTomNode, TomTomAPIKeyCredential, GetRasterTile, GetWMSMap

KEY = "tomtom-test-secret-12345"
CASES = [
    ({"operation": "get_world_copyrights"}, "/map/1/copyrights.json", {"generalCopyrights": ["© TomTom"]}),
    ({"operation": "get_copyright_caption"}, "/map/1/copyrights/caption.json", {"copyrightsCaption": "© TomTom"}),
    ({"operation": "get_area_copyrights", "minLon": -179.1506, "minLat": 18.9117, "maxLon": -66.9406, "maxLat": 71.441}, "/map/1/copyrights/-179.1506/18.9117/-66.9406/71.441.json", {"regions": []}),
    ({"operation": "get_tile_copyrights", "zoom": 2, "X": 1, "Y": 2}, "/map/1/copyrights/2/1/2.json", {"regions": []}),
    ({"operation": "get_static_image", "center": "4.899886,52.379031"}, "/map/1/staticimage", b"\x89PNG\r\n\x1a\nimage"),
    ({"operation": "get_vector_tile", "language": "en-GB"}, "/map/1/tile/basic/main/0/0/0.pbf", b"\x1a\x00"),
    ({"operation": "get_raster_tile", "format": "jpg", "style": "night"}, "/map/1/tile/basic/night/0/0/0.jpg", b"\xff\xd8\xffimage"),
    ({"operation": "get_wms_map", "bbox": "-0.489,51.28,0.236,51.686"}, "/map/1/wms/", b"\x89PNG\r\n\x1a\nimage"),
    ({"operation": "get_wms_capabilities"}, "/map/1/wms/", "<WMT_MS_Capabilities version='1.1.1'/>"),
    ({"operation": "get_wmts_capabilities"}, "/map/1/wmts/apiKey="+KEY+"/1.0.0/WMTSCapabilities.xml", "<Capabilities><ResourceURL template='?key="+KEY+"'/></Capabilities>"),
]


def make_node(config):
    node = TomTomNode("tomtom-test", "automation-tomtom", {}, config=TomTomNode.parse_config({"config": config, "credentials": {"api_key": KEY}}))
    node.emit = AsyncMock()
    return node


@pytest.mark.asyncio
@pytest.mark.parametrize("config,path,body", CASES)
async def test_each_operation_one_documented_request(monkeypatch, config, path, body):
    calls = []
    async def request(self, method, url, **kwargs):
        req = httpx.Request(method, url, params=kwargs.get("params"))
        calls.append(req)
        assert method == "GET"
        assert req.url.host == "api.tomtom.com"
        assert req.url.path == path
        if config["operation"] == "get_wmts_capabilities":
            assert not req.url.query
        else:
            assert req.url.params["key"] == KEY
        if config["operation"] == "get_wms_map":
            assert dict(req.url.params)["styles"] == ""
            assert req.url.params["request"] == "GetMap"
            assert req.url.params["version"] == "1.1.1"
        if config["operation"] == "get_wms_capabilities":
            assert req.url.params["request"] == "GetCapabilities"
        if isinstance(body, dict):
            return httpx.Response(200, json=body, request=req)
        return httpx.Response(200, content=body, headers={"content-type": "application/octet-stream" if isinstance(body, bytes) else "application/xml"}, request=req)
    monkeypatch.setattr(httpx.AsyncClient, "request", request)
    output = await make_node(config).execute({})
    assert len(calls) == 1
    assert output["status"] == "success"
    if isinstance(body, bytes):
        assert isinstance(output["file"], BinaryOutput)
        assert output["file"].data == body
    else:
        assert KEY not in str(output)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body,media", [(403, KEY+" rejected", "text/plain"), (200, '{"error":"denied"}', "application/json"), (200, '<ServiceExceptionReport/>', "application/xml"), (200, '', "image/png")])
async def test_failed_probe_never_reports_success_or_leaks_key(monkeypatch, status, body, media):
    async def request(self, method, url, **kwargs):
        return httpx.Response(status, text=body, headers={"content-type": media}, request=httpx.Request(method, url))
    monkeypatch.setattr(httpx.AsyncClient, "request", request)
    node = make_node({"operation": "get_raster_tile"})
    if status == 403:
        out = await node.execute({})
        assert out["status"] == "error"
        assert KEY not in str(out)
    else:
        with pytest.raises(ValueError):
            await node.execute({})


def test_manual_credential_type_default_and_invalid_inputs():
    assert TomTomAPIKeyCredential(api_key=KEY).credential_type == "tomtom_api_key"
    with pytest.raises(ValidationError):
        GetRasterTile(zoom=0, X=1)
    with pytest.raises(ValidationError):
        GetRasterTile(layer="hybrid", format="jpg")
    with pytest.raises(ValidationError):
        GetRasterTile(style="night", tileSize=512)
    with pytest.raises(ValidationError):
        GetWMSMap(bbox="2,3,1,0")


@pytest.mark.asyncio
@pytest.mark.parametrize("body", ["not XML", "<Other/>", "<ServiceExceptionReport/>"])
async def test_capabilities_reject_malformed_or_error_document(monkeypatch, body):
    async def request(self, method, url, **kwargs):
        return httpx.Response(200, text=body, request=httpx.Request(method, url))
    monkeypatch.setattr(httpx.AsyncClient, "request", request)
    with pytest.raises(ValueError):
        await make_node({"operation": "get_wms_capabilities"}).execute({})
