WildJar API v2 Postman evidence

`postman_examples.json` copies the selected collection items' saved responses,
including their original requests. The response bodies remain verbatim strings.
The `config` values come from those requests or response examples; only recipient
whitespace and numeric timeout representation are normalized for NoClick fields.

Source: https://developer.wildjar.com/api/collections/7393567/SVSLp8Rb?segregateAuth=true&versionTag=latest
Collection: WildJar API v2; published 2025-11-24; no version tag published.
Pinned collection SHA-256: f9bdda3695759e1ec26d843e40eeb419f00c5d88839debc84bb82d91951801e7

The operation set uses examples with published HTTP status and headers. Call-log,
transcript and address-book items with missing status or null headers are excluded.
The primary SMS send request declares `application/javascript`; its saved original
instead declares `application/json`. The node follows the primary declaration.
Lists return one provider-default page; no complete export is claimed. Write results
report provider acknowledgment, without claiming SMS delivery or readback verification.
