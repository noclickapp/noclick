# ClickFunnels deterministic evidence

`documented.json` contains one request and unaltered response example for every operation from ClickFunnels' [official OpenAPI](https://accounts.myclickfunnels.com/openapi.json). Each entry records its source URL and provider operation ID. The manifest, exact spec SHA-256, complete harness report and verdict are in `conformance.json`; the downloaded spec is pinned outside the repository in the run's `catalog/clickfunnels` directory.

The full-witness conformance run checks all 20 operations against spec version 2.0.0 and returns `ready: true`, with no blockers or advisories. Eighteen JSON responses validate as provider-authored. Removing a contact tag returns the documented bodyless 204. The published create-invoice example disagrees with its schema (null `external_id`, numeric strings in tax/discount fields, and nullable price interval fields): the harness therefore uses a generated schema-valid response for that operation. The mock test additionally parses the provider's original example unchanged, including its nulls and numeric strings. Neither the spec nor the provider fixtures were rewritten to obtain the verdict.

Run from `backend`:

```sh
python -m pytest nodes/tests/test_clickfunnels_node_mock.py tests/test_connection_evidence_coverage.py tests/test_oauth_scope_coverage.py -q
CONFORMANCE_WITNESS=full CONFORMANCE_CATALOG="$C" python -m tests.conformance.harness --provider clickfunnels --output "$C/report.json"
python3 "$RUN/verdict.py" "$C/report.json" "$C"
```

The conformance harness is overlaid for the run and is not part of this integration. Set `C` to the pinned catalog and `RUN` to the directory containing the verdict script. Use a Python environment with the harness dependencies installed.

For a manual account check, create a platform application in Team Settings → Developer Portal as described in [Getting Started](https://developers.myclickfunnels.com/docs/getting-started), then paste its API access token and workspace subdomain into the node's credential form. The account's own team names are read through `GET /teams` before saving. Select a team with List Workspaces to find the workspace ID, then configure an operation. Lists return one page plus `next_cursor`, accepted by the next call's `after` field. Creating external orders and paid invoices records purchases processed elsewhere; it does not charge a card.

The official icon is copied byte-for-byte from the ClickFunnels site's published favicon, linked by `https://brand.clickfunnels.com/`; the icon provenance sidecar records the source asset URL and SHA-256.
