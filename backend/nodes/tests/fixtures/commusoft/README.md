The operation fixtures use parameter and body values from Commusoft's published v2 API contract, version 1.0.0. Expected method, path and payload assertions are kept here so the HTTP tests do not derive their expectations from the node's route map.

Contract source: https://developer.commusoft.com/ (Export → OpenAPI 3.0, project 761702, branch 1114572). Pinned SHA-256: `ef726cea8b0a5acfaf7b3d7d11bdc6efea9739335e6970da25dc5a8e6ad67eeb`.

Authentication and regional roots: https://developer.commusoft.com/authentication-1985209m0.

Completion timestamp: https://developer.commusoft.com/requests-and-responses-1985359m0. The job-stage fixture supplies the schema-required `pipelineID` that the export's example omits. Appointment tests create single appointments, so `isRecurringEvent` is false.

List operations return one page in `data` with the original provider pagination envelope. Pass `pagination.nextCursor` as `after` for the next page; links in responses are never followed.
