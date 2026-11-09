# Kenect Text Messaging contract

This directory pins Kenect's own [Integrations API OpenAPI](https://integrations-api.kenect.com/q/openapi), version 1.0.1. `manifest.json` records its source and SHA-256; the offline tests validate write bodies against this unmodified contract.

The node exposes 15 operations. Reads cover authorized locations, organization users, one user, leads, broadcast messages, conversations, messages by phone, a conversation by phone, conversations by external contact ID, and attachment metadata. Writes send messages, request reviews through the current `/reviews/review-request` endpoint, submit leads, notify configured events, and sync contact batches. Every node operation performs exactly one published API operation. Partner template endpoints are excluded because those describe APIs implemented by the partner rather than Kenect messaging actions.

To connect manually, obtain the integration API key, API secret, and numeric Kenect location ID from the Kenect integration administrator. In the node's credentials form, enter those three fields and save. The connection probe lists locations authorized for the key; confirm the displayed location names. For a read check, list conversations with an explicit limit and offset. For a write check, send a text to a number you control and inspect the returned Kenect status and the message in Kenect.

List operations return one page. Use the exposed limit/offset or page/page-size fields to request subsequent pages; the node does not claim that a page is a complete export. Writes return the provider acknowledgement without automatic retries or a claim that the recipient received the text. Attachments must already have been uploaded using Kenect's pre-sign API; attachment metadata URLs are returned as data and never fetched.

Run the mock test module for offline regressions. The separate conformance harness checks all 15 requests and parsers against the pinned contract. Its full response witnesses are schema-generated, not provider-authored examples or live-account evidence.
