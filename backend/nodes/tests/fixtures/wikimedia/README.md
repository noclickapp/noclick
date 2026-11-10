These request parameters, request bodies, and response bodies are copied from
Wikimedia's Wikibase REST API OpenAPI 1.6:

https://raw.githubusercontent.com/wikimedia/mediawiki-extensions-Wikibase/master/repo/rest-api/src/openapi.json

Pinned SHA-256: `a0120001950dbf6e16ac792f0aeecef5f1fbdfd66e6bdf3fd519324db605da8a`.
Each fixture records the provider's operation ID and its source. The item-create
operation exposes labels, descriptions, and aliases; its fixture retains the
provider's complete example, including fields beyond this operation's UI.

The provider documents the default Wikidata deployment and pasted owner-only
OAuth2 bearer tokens here:

- https://www.wikidata.org/wiki/Wikidata:REST_API
- https://www.wikidata.org/wiki/Wikidata:REST_API/Authentication
- https://www.mediawiki.org/wiki/OAuth/Owner-only_consumers

The contract's `getItem` response declares `X-Authenticated-User` as optional.
Connection evidence reads Q24 and names that authenticated account when the
header is present. Its absence leaves the connection unverified. Unit tests use
an explicitly synthetic username header to exercise the authenticated branch;
the conformance run uses the provider's published body without inventing a
username. These fixtures are contract examples, not recorded live calls.

Trigger scope: this integration covers the pinned Wikibase REST API. Neither
the contract nor its REST API documentation offers webhook registration or a
list endpoint ordered/filtered by creation or update time. Its search endpoints
use text, language, limit, and offset. Wikimedia's separately documented
EventStreams service uses continuous SSE, outside the supported webhook/poll
families: https://wikitech.wikimedia.org/wiki/Event_Platform/EventStreams.
The separate MediaWiki Action API is outside this pinned contract.
