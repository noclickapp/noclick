# IP2Proxy conformance evidence

The pinned provider contract is version 1.0 from
https://api.swaggerhub.com/apis/ip2location/ip2proxy-proxy-detection/1.0.
`manifest.json` pins its SHA-256. The API has one GET / endpoint and no writes.
The eleven operations select its documented PX1–PX11 packages, each with a
different cumulative field set and credit cost (1–11 credits).

`lookup.json` is the JSON Web Service Query Example from
https://www.ip2location.com/web-service/ip2proxy (retrieved 2026-11-09).
`witnesses.json` preserves that whole example as JSON text, matching the
contract's text/html string response. The spec's all-empty placeholder is not
a successful API response: current docs specify response=OK. Numeric lastSeen
and creditsConsumed are preserved. No package-specific response is fabricated.
The same full provider example exercises each package parser; these tests do
not establish actual lower-package field availability or live account access.

`inputs.json` uses the provider's documented 201.42.237.89 example address.
`report.json` records all eleven request/parser checks; `verdict.json` has no
blocking or advisory items. The harness itself is supplied externally and is
not vendored here. Reproduce from backend with the fixture directory as
CONFORMANCE_CATALOG and CONFORMANCE_WITNESS=full, then run the verdict command.

The provider does not echo the queried IP. The node reports the requested IP
separately without claiming to independently verify it. Connection evidence
performs a one-credit PX1 query and proves key acceptance only. Existing
IP2Proxy keys are required; new registrations are closed. IP2Location.io keys
belong to a separate service. No provider sign-in or live query was performed.

| Operation | Package | Credits |
| --- | --- | --- |
| `get_proxy_status` | PX1 | 1 |
| `get_proxy_type` | PX2 | 2 |
| `get_proxy_location` | PX3 | 3 |
| `get_proxy_isp` | PX4 | 4 |
| `get_proxy_domain` | PX5 | 5 |
| `get_proxy_usage` | PX6 | 6 |
| `get_proxy_asn` | PX7 | 7 |
| `get_proxy_last_seen` | PX8 | 8 |
| `get_proxy_threat` | PX9 | 9 |
| `get_residential_proxy` | PX10 | 10 |
| `get_proxy_provider` | PX11 | 11 |
