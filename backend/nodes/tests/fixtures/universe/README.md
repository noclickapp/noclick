# Universe contract evidence

`manifest.json` pins the provider's REST, OAuth and Ticketmanager contracts by
SHA-256. The node implements eight REST/OAuth endpoints as ten workflow actions:
percent and fixed discounts have separate typed forms, and event guestlists have
a form requiring the event filter. Ticketmanager's installation/token-producing
operations are outside the workflow surface.

`report.json` is the unmodified full-witness conformance report; `verdict.json`
is its audited verdict. The raw verdict is **not ready**. `spec_defects.json`
maps every remaining blocker to provider documentation for review under the
integration author's documented-spec-contradiction exception. No response or
input was fabricated to turn the verdict green. `witnesses.json` copies the
published check-in response values, omitting the trailing non-JSON return symbol.

`requests.json` is an independent HTTP-boundary test fixture with synthetic IDs
and responses. It verifies request serialization and the parser's handling of
object envelopes; it is not presented as provider-authored conformance evidence.
No live-account verification is claimed.
