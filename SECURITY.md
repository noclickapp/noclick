# Security Policy

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability. Email
`security@noclick.com` with:

- the affected component and version or commit;
- reproduction steps or a proof of concept;
- the security impact you expect; and
- any known mitigations.

Please avoid accessing data that is not yours, disrupting a service, or using
automated scanners against systems you do not own. We will acknowledge a report
within five business days. We do not promise a bounty.

## Disclosure

We aim to publish a fix within **90 days** of acknowledging a report, and to
credit the reporter unless they ask otherwise. If a fix will take longer we will
say so and why, rather than let the date pass in silence. If a vulnerability is
already being exploited, we will publish as soon as there is something for
operators to act on, which may be shorter than 90 days and may precede a fix.

A reporter is free to publish after 90 days whether or not we have shipped. We
would rather know a deadline is approaching than be surprised by it.

## How a fix reaches this repository

Development happens in a private monorepo and this repository is produced from
it, so a security fix lands there first and appears here on the next export.
That means:

- **a fix can be public in a release before its commit is visible here**, and the
  commit that carries it will be part of a squashed re-sync rather than a
  standalone patch;
- **the advisory, not the diff, is the thing to read** — GitHub Security
  Advisories on this repository carry the affected versions and the upgrade;
- if you are pinned to a commit rather than a release, watch advisories rather
  than the commit log.

Nothing here is embargoed once an advisory is published; the delay is mechanical,
not a policy of withholding.

## Supported versions

Security work targets the current default branch and is included in the next
tagged release. Each advisory identifies its affected and fixed versions;
operators should upgrade to the latest release. No long-term-support release
line has been announced.

## Deployment responsibility

NoClick processes OAuth tokens, API keys, workflow input, and arbitrary
third-party data. Operators are responsible for TLS termination, access
controls, database backups, secret rotation, network isolation, and updates.
Keep `OUTBOUND_ALLOW_PRIVATE_IPS` disabled unless the instance runs in a
trusted network and private-network access from user-configured connectors is
intentional. `HTTP_NODE_ALLOW_PRIVATE_IPS` is retained only as a deprecated
compatibility alias.

See [docs/security-model.md](./docs/security-model.md) for the trust boundaries
and production hardening checklist.
