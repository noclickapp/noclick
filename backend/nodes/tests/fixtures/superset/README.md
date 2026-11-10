Superset conformance evidence

Evidence rung: `openapi`. The contract is Apache Superset's published v1
OpenAPI document, pinned at SHA-256
`399468df0ae31dcc821ef93cdd493b2e2e93ad28aa53a66f8e4f9ec9461ae08a`:
https://raw.githubusercontent.com/apache/superset/master/docs/static/resources/openapi.json

`conformance-report.json` and `conformance-verdict.json` record all 23 node
operations, including two poll triggers, checked against that contract. All
responses in this run were schema-generated, with no live service calls or
provider-authored response examples. `list_responses.json` contains synthetic
unit-test values using the same documented response fields; its manifest states
that distinction explicitly.

The manual credential takes a server origin and an existing API key, both
entered by the person connecting. The pinned contract declares Bearer API key
security on every exposed route. The server must support API keys. Account
evidence uses `GET /api/v1/me/`.

Poll triggers monitor the most recent 1–100 dashboards or charts on each tick.
Dashboard requests explicitly sort by `changed_on desc`. Chart requests preserve
Apache's `ChartRestApi.base_order = ("changed_on", "desc")`, because its explicit
`order_columns` does not include `changed_on`:
https://github.com/apache/superset/blob/master/superset/charts/api.py
The dashboard order is also documented in the implementation:
https://github.com/apache/superset/blob/master/superset/dashboards/api.py

Both item schemas declare `id`, `changed_on_utc`, their title, `changed_by_name`,
`url` and `description`. A fingerprint of ID and modification time feeds the
shared poll seen-set; registration baselines existing items, changes in the
poll configuration rebaseline, and empty polls do not wake the agent. Changes
that leave the configured window between polls can be missed. No webhook
registration or delivery contract is declared by this OpenAPI document.

Reproduce from backend with this contract directory as the catalog:

    CONFORMANCE_WITNESS=full CONFORMANCE_CATALOG=/path/to/catalog/superset python -m tests.conformance.harness --provider superset --output /path/to/catalog/superset/report.json
    python -m tests.conformance.verdict /path/to/catalog/superset/report.json /path/to/catalog/superset
