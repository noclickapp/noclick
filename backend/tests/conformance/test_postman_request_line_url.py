"""A Postman item whose URL string starts with its own method ("GET https://…") still names that URL."""
import httpx
import pytest

from tests.conformance.postman import PostmanContract


def collection(url, method="GET"):
    # Artificial contract for harness controls, never provider evidence.
    return {
        "info": {
            "name": "Request line",
            "version": "1",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "item": [{
            "name": "Read settings",
            "request": {"method": method, "url": url, "header": []},
            "response": [{"code": 200, "header": [], "body": '{"webhooks": []}'}],
        }],
    }


@pytest.mark.parametrize("url", [
    "GET https://app.example.test/xapi/control/{{userid}}/settings",
    "get  https://app.example.test/xapi/control/{{userid}}/settings",
    {"raw": "GET https://app.example.test/xapi/control/{{userid}}/settings"},
])
def test_the_items_own_method_before_the_url_is_not_part_of_it(url):
    contract = PostmanContract(collection(url))
    request = httpx.Request("GET", "https://app.example.test/xapi/control/u123/settings")
    contract.validate_request(request)
    assert contract.response(request, contract.match(request)[2]).json() == {"webhooks": []}


def test_another_methods_name_before_the_url_still_matches_nothing():
    contract = PostmanContract(collection("POST https://app.example.test/xapi/control/{{userid}}/settings"))
    with pytest.raises(ValueError, match="No spec operation"):
        contract.match(httpx.Request("GET", "https://app.example.test/xapi/control/u123/settings"))
