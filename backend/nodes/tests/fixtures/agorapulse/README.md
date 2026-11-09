These test values exercise the provider's published item schemas, rather than
claiming to record a live account. Both inbox `AbstractItem` and listening
`AbstractListeningItem` declare every field in `items.json`, with their
respective creator schemas requiring `id` and `name`.

Contract: https://api.agorapulse.com/docs/open-api.yml (version 1.0).
The full conformance harness independently generates and validates provider
responses from that pinned contract; no catalog witness overrides are used.
