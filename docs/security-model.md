# Security model

NoClick executes workflows that can call external services and process
untrusted input. Treat the backend as a privileged service.

## Trust boundaries

- Browser sessions are authenticated by Supabase; backend authorization still
  checks ownership or explicit sharing for every resource.
- Stored credentials are encrypted with an operator-held Fernet key. Database
  access alone should not reveal plaintext credentials.
- Model-provider credential rows are reduced to the selected provider's known
  keys at execution time, including legacy and imported rows. Proxy and generic
  endpoint overrides are discarded; the supported Azure and Databricks base
  URL fields must use HTTPS on their provider-owned tenant domains. User-level
  Vertex AI credentials accept sanitized inline service-account JSON only, not
  a backend filesystem path or external-account credential source.
- Workflow and workspace links use scoped, expiring capabilities. A capability
  is a secret and must not be logged or placed in analytics.
- Collaboration-room tokens are workflow-scoped and carry a viewer or editor
  role. Viewers cannot change graph state or stop executions, and user-directed
  events travel over the authenticated Socket.IO session rather than a
  user-identifier URL.
- Platform-mediated requests whose destination is user-configured (including
  HTTP, MCP, feed, import, self-hosted service, PostgreSQL, and MongoDB
  connectors) resolve and reject non-public targets by default. HTTP redirect
  hops are revalidated. Plain MongoDB URIs outside Atlas are additionally
  forced into single-host direct mode so a public seed cannot advertise private
  replica members. Managed MongoDB topology is limited to TLS-verified Atlas
  `*.mongodb.net` hosts. Arbitrary MongoDB replica/SRV topology requires the
  explicit private-network opt-out and an operator-controlled egress firewall.
  Trusted installations can explicitly opt in to LAN access with
  `OUTBOUND_ALLOW_PRIVATE_IPS=1`.
- Agent and code execution can run user-directed commands. Their subprocess
  traffic is not intercepted by the application-level URL guard; enforce an
  outbound network policy as part of the OS, container, or VM isolation.
- Authored HTML/React interface blocks execute in a sandboxed opaque-origin
  iframe. The host accepts bridge messages only from that exact frame and
  applies workflow and read-only authorization; do not add `allow-same-origin`,
  popup, or top-navigation permissions without a new threat-model review.
- Interface code is still workflow-author code: it can call external networks
  and can request workflow data and actions exposed by the SDK. Only open
  editable workflows from authors you trust, limit browser egress where that
  trust is insufficient, and treat every newly exposed SDK method as a
  privileged data-flow decision. Read-only views deny credential discovery and
  all mutating or execution methods.
- Webhook, OAuth, and inbound-email routes receive hostile internet input and
  must remain behind TLS, request limits, and provider signature checks.

## Operator controls

- Use unique high-entropy signing and encryption keys.
- Restrict service-role and database credentials to the backend.
- Keep browser-exposed configuration free of secrets.
- Segment execution workers from databases and internal control planes.
- Apply egress controls where workflows must not reach arbitrary hosts.
- Redact workflow inputs, tool arguments, tokens, and capabilities from logs and
  traces.
- Test restoration of both data and encryption-key backups.
- Patch the OS, container images, Python packages, and JavaScript packages.

The project cannot make arbitrary user-authored code safe inside a fully trusted
host process. Operators serving mutually untrusted users must add a hardened
sandbox boundary appropriate to their threat model.
