# Synap webhook fixtures

Field layouts are transcribed from Synap Academy's published TypeScript interfaces. Values are synthetic test values, not recorded account data; no undocumented envelope or field is assumed.

- user-registered.json: https://academy.synap.ac/doc/integrations/webhooks/user-registered-webhook
- user-updated.json: https://academy.synap.ac/doc/integrations/webhooks/user-updated-webhook
- attempt-completed.json: https://academy.synap.ac/doc/integrations/webhooks/attempt-completed-webhook

Synap documents Basic delivery authentication at https://academy.synap.ac/doc/integrations/webhooks. The API event name is `attempt.complete` in the pinned v3 OpenAPI enum; the Academy's overview calls it `attempt.completed`. Registration uses the API contract's enum.

learning-record-updated.json and learning-record-deleted.json are verbatim provider examples from https://academy.synap.ac/doc/integrations/webhooks/learning-record-webhooks.md. Their values are preserved, including the provider-published expired file URL.
