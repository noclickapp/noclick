"""Generate ClickSend v3 actions from its pinned official SDK Swagger file."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.request import urlopen

import yaml


SOURCE_COMMIT = "06edc171aa543cc54fe22a94cc2bc0c0a53392ef"
SOURCE_URL = (
    "https://raw.githubusercontent.com/ClickSend/clicksend-go/"
    f"{SOURCE_COMMIT}/api/swagger.yaml"
)
OUTPUT = Path(__file__).with_name("catalog.json")
METHODS = {"get", "post", "put", "patch", "delete"}
# Account signup, password reset, activation, and API-key rotation require
# secret material that workflow graph config would store in plaintext.
EXCLUDED_OPERATION_IDS = {
    "AccountPost",
    "AccountVerifySendPut",
    "AccountVerifyVerifyByActivationTokenPut",
    "ForgotPasswordPut",
    "ForgotPasswordVerifyPut",
    "ForgotUsernamePut",
    "ResellerAccountsByClientUserIdPut",
    "ResellerAccountsPost",
    "SubaccountsBySubaccountIdPut",
    "SubaccountsPost",
    "SubaccountsRegenApiKeyBySubaccountIdPut",
    "VerifyAllowedEmailAddressGet",
    "RechargeCreditCardGet",
    "RechargeCreditCardPut",
}


def _snake_case(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _resolve(spec: dict, schema: dict) -> dict:
    while "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/definitions/"):
            raise ValueError(f"Unexpected ClickSend schema reference: {ref}")
        schema = spec["definitions"][ref.split("/")[-1]]
    return schema


def _body_required_fields(spec: dict, schema: dict) -> list[str]:
    schema = _resolve(spec, schema)
    required = set(schema.get("required", []))
    for part in schema.get("allOf", []):
        required.update(_body_required_fields(spec, part))
    return sorted(required)


def catalog_from_spec(spec: dict) -> dict:
    operations = []
    seen = set()
    for path, methods in spec["paths"].items():
        for method, definition in methods.items():
            if method not in METHODS:
                continue
            if definition["operationId"] in EXCLUDED_OPERATION_IDS:
                continue
            name = _snake_case(definition["operationId"])
            if name == "account_get":
                name = "get_account"
            if name in seen:
                raise ValueError(f"Duplicate ClickSend action: {name}")
            seen.add(name)
            parameters = definition.get("parameters", [])
            path_params = re.findall(r"\{([^{}]+)\}", path)
            required_query = sorted(
                p["name"]
                for p in parameters
                if p["in"] == "query" and p.get("required")
            )
            body = next((p for p in parameters if p["in"] == "body"), None)
            operations.append(
                {
                    "name": name,
                    "label": definition.get("summary")
                    or name.replace("_", " ").title(),
                    "description": (definition.get("description") or "").split("\n")[0][
                        :500
                    ]
                    or f"{method.upper()} {path}",
                    "category": (definition.get("tags") or ["Other"])[0],
                    "method": method.upper(),
                    "path": path,
                    "path_params": path_params,
                    "required_query": required_query,
                    "body_required": bool(body and body.get("required")),
                    "body_required_fields": (
                        _body_required_fields(spec, body["schema"]) if body else []
                    ),
                    "has_body": body is not None,
                }
            )
    return {
        "source_url": SOURCE_URL,
        "operations": sorted(operations, key=lambda op: op["name"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-file", type=Path)
    args = parser.parse_args()
    source = (
        args.source_file.read_bytes()
        if args.source_file
        else urlopen(SOURCE_URL).read()
    )
    catalog = catalog_from_spec(yaml.safe_load(source))
    OUTPUT.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {len(catalog['operations'])} ClickSend actions to {OUTPUT}")


if __name__ == "__main__":
    main()
