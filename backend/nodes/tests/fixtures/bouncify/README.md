# Bouncify contract evidence

`responses.json` contains the provider's successful examples from the four v1.0
OpenAPI descriptions, with the HTTP status line removed from the PATCH example.
Tests replay these offline; no account credentials or live API calls are used.

The provider publishes seven operations. This integration exposes all seven,
including the documented JSON-array variant of bulk upload. It does not invent
additional endpoints to reach a larger operation count.

## Published specification contradictions

- Bulk upload's schema requires both `local_file` and `RAW_BODY` and declares
  `auto_verify` boolean. The same provider's “Option 2: Array of emails” example
  instead sends `emails` objects and `auto_verify: "true"` directly as JSON.
  The node follows that example, preserving optional extra columns:
  https://bouncify.readme.io/reference/upload-a-bulk-email-list.md
- GET, PATCH and DELETE are declared at `/bulk` with a required `job_id` path
  parameter, but the path omits `{job_id}`. The provider's code samples send
  `/v1/bulk/jobId`. The node uses `/v1/bulk/{job_id}`:
  https://bouncify.readme.io/reference/check-job-status-of-a-bulk-email-list.md
  https://bouncify.readme.io/reference/start-verifying-bulk-email-list.md
  https://bouncify.readme.io/reference/delete-a-bulk-email-list.md
- PATCH models a `RAW_BODY` string while its Python/Node examples send
  `{"action":"start"}` as the JSON body. The node follows those examples.
  The successful response means verification was requested, not completed.
- Download describes `RAW_BODY` but documents `filterResult` as the actual JSON
  object. The schema permits this property, so the request conforms:
  https://bouncify.readme.io/reference/download-the-result-of-bulk-email-list.md

The account read exposes only a credit balance, without an account identity.
Connection evidence therefore honestly declares reachability. Verification
operations can consume credits; no request is automatically retried. Deletion
returns the provider's acknowledgement without claiming deletion completed.
CSV downloads return the shared `BinaryOutput` marker.
