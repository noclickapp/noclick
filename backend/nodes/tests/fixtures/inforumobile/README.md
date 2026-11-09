InforUMobile contract and saved examples

Source: https://documenter.gw.postman.com/api/collections/15332030/TzeWFTF1
Provider documentation: https://apidoc.inforu.co.il/
Collection published id: TzeWFTF1 (no version is published).
Pinned collection SHA-256: 0ebae43c6c42fdcafc4a4700f6915651a2e137d7061c35c576f09eda9093c218

`postman_examples.json` contains the complete, unmodified collection items for
our twenty operations, including request descriptions and every saved response.
The tests replay all saved responses, including the contact upsert's 401, through
the native node factory. No response schemas have been inferred from examples.

Authentication contract contradiction

The collection declares `noauth` while its literal Authorization headers say
`Your Base Credentials`, `Your Base Credential`, or
`Basic USER:TOKEN (Encode Base64)` (sometimes with a leading space).
Those are instructions, not actual Authorization header values. The current
provider documentation at https://apidoc.inforu.co.il/ serves this collection;
its Get Quota documentation explicitly says Basic authentication, and the
contact endpoint headers explicitly instruct Base64 encoding of USER:TOKEN.
The implementation sends `Basic base64(username:api_token)` to the fixed
`https://capi.inforu.co.il` origin. Sending the literal published instruction
would reject real credentials. The unchanged conformance harness interprets
those instructions as exact string requirements, which is a documented contract
exception, not permission to send fake credentials or alter the pin.

Media types match the saved requests. POST routes retain case and trailing
slashes. Lists return a single provider page and preserve LastFetchedId in data;
there are no automatic pagination requests or retries. Contact upsert is limited
to ten records so the response is final, rather than requiring asynchronous job
polling. Group deletion defaults to preserving contacts. Message/campaign sends
require explicit recipients. Connecting only reads the account's groups.

The saved WhatsApp chat and email campaign list/detail examples have plain JSON
bodies with gzip response headers. Those operations are excluded because those
saved responses cannot be replayed verbatim by HTTPX. Their headers and bodies
have not been rewritten or substituted.
