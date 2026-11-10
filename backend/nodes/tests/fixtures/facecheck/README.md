`openapi.json` is the unmodified provider OpenAPI v1.02 downloaded from
https://facecheck.id/Swagger/v1/swagger.json and pinned by the pipeline catalog.
SHA-256: f7b69df082c0c237a0c6bede3bc358679624b1842d4eb1d16c0d15e4814519d8.

The mock tests use the contract's search ID and InfoResponse property examples.
Other response bodies and image bytes in the tests are synthetic boundary cases,
not live recordings or provider-authored response examples.

https://facecheck.id/en/Face-Search/API documents raw Authorization tokens,
multipart images, demo mode, progress and errors returned inside HTTP 200 JSON.
The contract and docs expose no webhook registration and no list endpoint with
created/updated ordering or filtering; no automation trigger is supported.
