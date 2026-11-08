# TalentHR Postman evidence

Source: https://www.postman.com/collections/32971705-282b1908-49ef-4074-8ea7-67fdb51c9b4a

Version: not published. Pinned Postman collection SHA-256:
`bec140f4ebced1041ea8540208253a74fd3e69bbe76ba7f3627dbe62bbdfc6e6`.

`postman_examples.json` copies the 20 implemented items' published requests,
descriptions and every saved response, including errors. Response bodies remain
the publisher's exact strings. Tests replay all 44 through the native runner.
`inputs.json` uses the collection's body-table examples and saved response IDs.
No live account was used. Department listing proves the connected tenant.

List operations return one provider page. Outputs preserve the complete JSON
object under `data`, including the unusual quoted keys in the published
employee time-off request listing. Callers page explicitly with offset and limit.
The hire operation uses TalentHR's default invitation and onboarding behavior,
which can email the new employee and task owners, as its description explains.

Rehire, location creation/update and time-off creation are outside this initial
release: the collection's saved requests conflict with its descriptive request
contract, or include HTTP 200 business errors the harness cannot judge. No
response or contract was corrected to obtain a pass.

`conformance_report.json` and `conformance_verdict.json` retain the complete
harness result and machine verdict. This is Postman-checked evidence, weaker
than OpenAPI schema validation.
