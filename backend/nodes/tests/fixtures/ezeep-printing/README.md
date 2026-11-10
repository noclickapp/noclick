# ezeep Printing evidence

Evidence rung: published OpenAPI, v1. Source: https://api2.ezeep.com/printing/v1/schema/

Pinned SHA-256: b89511f1ff67d321b7f0b04fa806f17ba1a33d027f3bf3e60fa2c0e83f081178. The contract bytes were not changed. No live credentials were supplied or used.

The node exposes 24 fixed management operations from that contract and one successful-print-job webhook trigger. Document submission uses a separate ezeep Print API and is outside this contract.

The webhook request payload and registration response are copied completely from the provider's [Webhooks documentation](https://apidocs.ezeep.com/ezeepblue/api/rest_api/webhooks/README.html). The trigger subscribes only to printjob_succeeded, the event for which the provider publishes a complete delivery example.

See spec_defects.json for the two documented contract defects. The conformance report checks every management request and delivers the published event; the missing registration route is the only remaining blocker. The signature harness only supports HMAC, whereas ezeep uses optional HTTP Basic configured when registering. This node always registers with Basic and a random password, stored in the platform's signing-secret slot. Unit tests check correct, missing, malformed and incorrect credentials.

OAuth uses ezeep's [confidential authorization-code flow](https://apidocs.ezeep.com/ezeepblue/auth/auth_code_flow/auth_code_flow.html), Basic client authentication and rotating refresh tokens. Identity is the pinned contract's GET /printing/v1/users/me/. Production requires a registered ezeep OAuth client, with EZEEP_PRINTING_CLIENT_ID, EZEEP_PRINTING_CLIENT_SECRET and EZEEP_PRINTING_REDIRECT_URI configured. No app was registered or account signed into during this build.
