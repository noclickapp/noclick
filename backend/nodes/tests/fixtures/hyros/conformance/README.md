# Hyros contract evidence

`openapi.yaml` is the unmodified Hyros REST API 1.46 contract from
https://api-docs.hyros.com/specs/hyros-api.yaml. Its source, version and SHA-256
are pinned in `manifest.json`. The credential is a harness placeholder only.

`inputs.json` contains complete product configurations using the provider's
published examples at https://api-docs.hyros.com/ai-context/rest-api.txt. These
replace generated product names shorter than Hyros permits. The update's
product id comes from the documented processed-product request-status example.

`report.json` records each native operation's request and contract validation;
`verdict.json` records the source-audited merge verdict. The conformance harness
is supplied externally and is deliberately not vendored with this integration.
This evidence is offline validation; it does not claim a live-account test.
