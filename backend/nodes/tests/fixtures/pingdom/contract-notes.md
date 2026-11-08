# Pingdom API 3.1 contract evidence

Source: https://docs.pingdom.com/API_3.1.yaml

Version: 3.1. SHA256: `e78042fccf24554984a6f625c3802c6977e135c2aa1bd6ee8b054e212e5511ca`. The current official download matched the catalog pin on 2026-11-08.

## POST /checks

The request body oneOf has eight protocol branches, including HTTP, SMTP, POP3 and IMAP branches with no required properties and no discriminating type constraint. A documented HTTP request matches multiple branches and is rejected. The published JSON request example name=check_google, host=www.google.com, type=http is itself rejected by that schema.

## PUT /checks/{checkid}

The request body repeats the eight overlapping protocol oneOf branches without discriminating type constraints. A documented partial update (name=google_check, host=www.google.com, paused=false) matches multiple branches and is rejected despite the published update example.

## GET /checks/{checkid}

The response schema oneOf has eight protocol-specific check envelopes, with no required properties or additionalProperties restriction. A normal documented HTTP check envelope also satisfies the other protocol branches, preventing a spec-valid response witness. The node retains the JSON envelope, including omitted optional attributes as permitted by the JSON Responses section.

All three are provider schema contradictions, retained without weakening or editing the contract. The other 17 operations pass conformance. Documented maintenance inputs replace synthetic equal start/end timestamps.
