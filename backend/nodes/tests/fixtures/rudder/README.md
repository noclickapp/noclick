`node.json` is the unmodified JSON response in Rudder’s own REST API test,
“Get node (full)”. Source retrieved 2026-11-11:
https://github.com/Normation/rudder/blob/a0efc05784e2ec2af75945fbfb13a8f5b6325352/webapp/sources/rudder/rudder-rest/src/test/resources/api/api_nodes.yml

The inventory poll tests reuse that exact node object in the list envelope
specified by https://docs.rudder.io/api/v/12/openapi.yml (`GET /nodes`), then
change the timestamp/ID to simulate subsequent inventory revisions. These
mutated cases test deduplication, not a claim of recorded provider traffic.
The primary conformance evidence is the pinned v12 OpenAPI, not this fixture.
