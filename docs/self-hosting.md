# Self-hosting NoClick

Everything you need to run NoClick on your own infrastructure: how the two
processes fit together, which environment variables each one reads, and how to
connect model providers, integrations, and storage.

If you just want it running locally, `make local` does all of this for you —
skip to [What `make local` sets for you](#what-make-local-sets-for-you) to see
what it configured, then come back when you want to change something.

---

> **Python 3.12 is required.** Some pinned dependencies don't yet publish
> wheels for 3.13, so installing on 3.13 fails while building from source.

> **Give Docker at least 8 GiB** if you build the images yourself. The
> frontend's production bundle asks Node for a 4 GiB heap, and everything
> already running counts against the same limit — under that, the build spends
> twenty minutes getting to `ResourceExhausted: cannot allocate memory`, which
> names neither the cause nor the fix. `scripts/noclick-setup.sh` warns you
> before you spend the twenty minutes.

## Versions

`main` moves whenever work lands upstream. It is the development line: current,
and worth reading, but not what you should point a deployment at — it can change
under you between two `docker compose up`s, migrations included.

Releases are tags, and each one publishes a single-origin image. A direct
container run needs a runtime env file containing the required backend and
frontend values documented below:

```bash
# The whole application on one port, against a database you already have
docker run -e POSTGRES_URL='postgres://…' -e VITE_PUBLIC_URL='https://noclick.example.com' \
  -p 8080:8080 ghcr.io/noclickapp/noclick:0.2.1
```

A database URL is all that image needs. It runs the auth layer itself — GoTrue
and PostgREST, served on its own origin under `/auth/v1` and `/rest/v1` — so on
first boot it prepares the database (roles, schemas, extensions, then both sets
of migrations) and mints this instance's own secrets, keeping them in a
`noclick_instance` schema so a redeploy reuses them.

Set any of those secrets in the environment and yours is used instead, which is
the stronger arrangement where your platform has a secret store: an operator
holding `CREDENTIALS_ENCRYPTION_KEY` outside the database keeps stored
credentials unreadable to anyone who only has a copy of it. Set `SUPABASE_URL`
and the embedded stack does not run at all — the instance uses that project,
which is the arrangement described under [Required configuration](#required-configuration).

The compose stack pulls the released backend rather than building it. Pin it:

```bash
NOCLICK_VERSION=0.2.1 docker compose up -d
```

Unset, `NOCLICK_VERSION` resolves to `latest`, which is the newest _release_ —
never main. Pin it anyway: when you report a problem, the version is the first
thing either of us needs.

> **Pre-release database reset:** databases initialized from a repository
> candidate before 2026-08-23 are not upgradeable in place. Back up any data you
> need, recreate the candidate database (or its Docker volume), and let
> `docker/bootstrap.py` apply the released schema to the empty database. The
> candidate's squashed migration changed before GA, and an automatic repair
> would have to guess which existing data is safe to discard. Migration versions
> are append-only starting with the first public release.

The frontend is still built locally, and deliberately: `docker/frontend.Dockerfile`
compiles `VITE_*` into the browser bundle, so an image built without your URLs
would be wrong for everyone who pulled it. The single-origin image avoids the
question entirely — it bakes no URL and asks the origin it was served from,
which is why that one can be published and why the one-click deploys use it.

## Hosted deployments

The hosted paths all run the same single-origin image: one backend, one
frontend, and nginx in one container on port 8080. They intentionally create
exactly one application instance because the community scheduler and realtime
room state are process-local. Each path runs the idempotent database bootstrap
before serving traffic.

There is nothing to fill in. Railway and Render create the Postgres database
alongside the application; DigitalOcean asks you to create a managed cluster
named `noclick-db` in the app's region first, because the only database its
platform creates for you is a development one whose user cannot initialise the
auth layer. The application does the rest on first boot.

### Browser-based deploys

| Provider | Deploy | Configuration |
| --- | --- | --- |
| Render | [Deploy](https://render.com/deploy?repo=https://github.com/noclickapp/noclick) | [`render.yaml`](../render.yaml) — database, disk, and generated secrets |
| Railway | [Deploy](https://railway.com/new/template/noclick?utm_medium=integration&utm_source=button&utm_campaign=noclick) | [`railway.template.json`](../railway.template.json) — database, volume, and generated secrets |
| DigitalOcean | [Deploy](https://cloud.digitalocean.com/apps/new?repo=https://github.com/noclickapp/noclick/tree/main) | [`.do/deploy.template.yaml`](../.do/deploy.template.yaml) — binds a managed cluster named `noclick-db` that you create first (App Platform creates only a development database, whose user cannot host the auth layer) |

Review the generated plan before accepting it: scheduled workflows require the
single application instance to keep running rather than scale to zero, and the
database is what everything else is derived from — back it up.

**Where this instance's keys live** differs by provider, because their
capabilities do. Render and Railway generate every secret and hold it in the
service's own environment. App Platform can generate nothing, so a
DigitalOcean instance mints its own on first boot and keeps them in its
database — the only place they survive a redeploy there. To hold the
credential-encryption key outside the database instead, set
`CREDENTIALS_ENCRYPTION_KEY` on the service before the first deploy.

Object storage is not created by any of them, so file and media features stay
off until `OBJECT_STORAGE_ENDPOINT`, `OBJECT_STORAGE_ACCESS_KEY_ID` and
`OBJECT_STORAGE_SECRET_ACCESS_KEY` are set. Any S3-compatible provider works.

### Fly.io

Fly.io has retired its browser-based application launcher, so its supported
path uses `flyctl` and the checked-in [`fly.toml`](../fly.toml). Change the
placeholder `app` value to a globally unique name, then run:

```bash
fly postgres create --name noclick-db     # or bring your own database URL
fly postgres attach noclick-db            # sets DATABASE_URL on the app
fly secrets set POSTGRES_URL="$(fly ssh console -C 'printenv DATABASE_URL')"
fly deploy
```

Everything else the instance mints for itself on first boot. Keep a copy of the
credential-encryption key it generates — `fly ssh console -C 'printenv
CREDENTIALS_ENCRYPTION_KEY'` — or set your own before the first deploy.

There is no release command: the auth server that has to migrate first runs
inside the image, so the instance prepares its own database as it starts.
Autostop is disabled because an idle HTTP service can still have cron work to
execute.

## The shape of a deployment

NoClick is two processes plus a Postgres database:

| Process      | What it is                                        | Serves                                                                     |
| ------------ | ------------------------------------------------- | -------------------------------------------------------------------------- |
| **Backend**  | Python (FastAPI + Socket.IO), `backend/server.py` | The API, the realtime socket, workflow execution, webhooks, the MCP server |
| **Frontend** | Remix (Node), `frontend/`                         | The editor UI, published interfaces, OAuth authorize/callback routes       |
| **Database** | Postgres 15+                                      | Everything persistent. Supabase provides auth on top of it                 |

The frontend talks to the backend over HTTP and WebSocket. Both talk to the
database. Both need to agree on your Supabase project.

Run exactly **one backend process**. The community scheduler and realtime
Socket.IO room state are in-process; multiple backend workers would each tick
the same schedules and a reconnect could land on a process that does not own
the socket. Scale the frontend independently if needed, but keep Uvicorn at
`--workers 1` until a shared scheduler and Socket.IO adapter are configured.

**Why some variables appear on both sides**: the frontend starts OAuth flows
(it needs a provider's _client ID_ and _redirect URI_), and the backend
completes them and refreshes tokens (it needs the _client ID_ and _client
secret_). Secrets never reach the browser — anything the browser sees is
prefixed `VITE_`.

---

## Required configuration

These are the only variables you _must_ set. Everything else adds capability.

This is the from-source shape: two processes you run yourself, against a
Supabase project you created. The single-origin image needs far less of it — a
database URL, and it derives or generates the rest (see
[Hosted deployments](#hosted-deployments)). The `SUPABASE_*` rows below are how
you point _either_ shape at an external project instead.

### Backend (`backend/.env`)

| Variable                                      | What it does                                                                                                                                                                                                                               |
| --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `POSTGRES_POOLER_URL`                         | Connection string used by all runtime queries. Point it at your pooler if you have one, or the same URL as below if you don't.                                                                                                             |
| `POSTGRES_URL`                                | Direct connection, used for migrations and anything needing session state.                                                                                                                                                                 |
| `SUPABASE_URL`                                | Your Supabase project URL — used to verify auth tokens and read user records.                                                                                                                                                              |
| `SUPABASE_JWK_URL` _or_ `SUPABASE_JWT_SECRET` | How the backend verifies login tokens. Modern Supabase signs with a rotating key: prefer the JWKS URL (`$SUPABASE_URL/auth/v1/.well-known/jwks.json`). Older/self-managed setups that sign symmetrically use the JWT secret.               |
| `SUPABASE_SECRET_KEY`                         | Service-role key, for admin reads of the auth user table.                                                                                                                                                                                  |
| `CREDENTIALS_ENCRYPTION_KEY`                  | Fernet key encrypting every stored credential at rest. Generate once with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. **Back it up — losing it makes every saved credential unreadable.** |
| `WORKFLOW_JWT_SECRET`                         | Signs the short-lived tokens the browser uses to join a workflow's realtime room. Any long random string.                                                                                                                                  |
| `NOCLICK_LOCAL`                               | Set to `1` for self-hosted. Switches the event relay and scheduler to in-process implementations instead of the hosted cloud services.                                                                                                     |

### Frontend (`frontend/.env`)

| Variable            | What it does                                                                                                                      |
| ------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `VITE_API_URL`      | Where the browser reaches the backend, e.g. `https://api.example.com`.                                                            |
| `VITE_RELAY_URL`    | Realtime endpoint. Self-hosted, this is your backend with a `/relay` path and a `ws(s)://` scheme: `wss://api.example.com/relay`. |
| `VITE_PUBLIC_URL`   | The frontend's own public URL. Used for OAuth redirects and install-aware links.                                                  |
| `SUPABASE_URL`      | Same project as the backend.                                                                                                      |
| `SUPABASE_ANON_KEY` | Public anon key — safe in the browser.                                                                                            |
| `SESSION_SECRET`    | Signs the frontend's own session cookie. Any long random string.                                                                  |

---

## Models: making agents work

Agent nodes need a model. There are two kinds, and they get credentials
differently.

**API-model agents** run in-process. Users connect a provider key through the
UI (Settings → Credentials), so nothing is required in your environment. If you
prefer a shared server-side key, set the matching variable and every agent can
use it:

| Variable                            | Provider                            |
| ----------------------------------- | ----------------------------------- |
| `OPENROUTER_API_KEY`                | OpenRouter (widest model selection) |
| `OPENAI_API_KEY`                    | OpenAI                              |
| `GEMINI_API_KEY` / `GOOGLE_API_KEY` | Google                              |

The backend also uses `OPENROUTER_API_KEY`, when configured, for optional
AI-curated output-field suggestions in the workflow editor. To produce those
suggestions, it sends the node type, operation, output schema, and a depth- and
length-limited sample of that node's output to OpenRouter. With
`NOCLICK_LOCAL=1`, a missing or blank `OPENROUTER_API_KEY` disables this
enrichment completely: ordinary node runs make no suggestion request. Keys
connected by individual users in the UI are not used for this background
feature.

**The workflow builder** needs a model too. It runs on `WORKFLOW_BUILDER_MODEL`
when set, else on `openrouter/openai/gpt-5-mini` with `OPENROUTER_API_KEY` (or
`openai/gpt-5-mini` when only `OPENAI_API_KEY` is set). Nothing has to be in the
environment: the first time the builder finds its key missing it asks for one
in the chat, and Settings → OAuth Apps & Keys holds the instance's keys after
that. Environment variables take precedence over saved keys.

**Harness agents** (Claude Code, Codex, opencode, hermes, OpenClaw) run the
real CLI as a subprocess on the machine running the backend, signed in as
whatever the agent node carries: a ChatGPT or Claude subscription sign-in
(Connect in the node's credential panel), an API key, or — with nothing
attached — the account that CLI is already signed in to on the server. The
single-origin image ships `codex`, `claude` and `opencode`; a from-source
install needs them on the backend's PATH:

```bash
# whichever you want available
npm install -g @anthropic-ai/claude-code   # then: claude   (sign in)
npm install -g @openai/codex               # then: codex    (sign in)
npm install -g opencode-ai
npm install -g openclaw

# hermes pins openai==2.24.0, which conflicts with the backend's own
# dependencies — install it isolated, NOT into the backend's environment:
pipx install 'hermes-agent[mcp]'          # or a dedicated venv on your PATH
```

Installing hermes into the same virtualenv as the backend downgrades `openai`
and breaks agent runs. Any install that puts a `hermes` binary on the PATH of
the process running the backend works.

Each conversation gets its own named workspace directory under
`~/.noclick/volumes/`, so sessions resume across turns. Tools you wire into the
agent are served to the CLI over a local MCP endpoint automatically.

Model selection differs per harness: each runs whatever model its CLI is
configured for, and a model your installed version doesn't recognise fails with
the CLI's own message (for example "requires a newer version of Codex") — upgrade
the CLI or pick a model it supports.

> **Note on hermes**: its one-shot mode can start before its tool connection is
> ready. NoClick detects a turn that ran without tools and re-runs it once. You
> may occasionally see a turn take twice as long as a result.

---

## Accounts and sign-in

NoClick always requires an account, self-hosted included. That isn't
ceremony: every workflow, credential, and connection is owned by a user,
row-level security in the database enforces that ownership, and sharing and
collaboration are built on it. An instance reachable on your network with no
login would expose every stored credential.

**First run**: open the app and choose _Sign up_ — the local Supabase confirms
the address instantly, so you're straight into the dashboard. The first
account is a normal user; subsequent people can sign up too, or you can invite
them.

**Bot protection is off by default.** The signup form supports Cloudflare
Turnstile but only enables it when you configure a site key. If you expose
signup on the public internet, set `VITE_CLOUDFLARE_TURNSTILE_SITE_KEY` in the
frontend and enable captcha in your Supabase auth settings so the token is
actually verified. Setting `VITE_DISABLE_CAPTCHA=true` keeps it off explicitly.

---

## Connecting integrations (OAuth)

Integrations that use OAuth need _your own_ OAuth app with the provider —
NoClick doesn't ship shared credentials. The pattern is identical for all of
them:

1. Create an OAuth app in the provider's developer console.
2. Set the redirect URI to `{VITE_PUBLIC_URL}/api/auth/{provider}/callback`
   (for example `https://app.example.com/api/auth/linear/callback`).
3. Set three variables:

```bash
# frontend/.env  — starts the flow
LINEAR_CLIENT_ID=...
LINEAR_REDIRECT_URI=https://app.example.com/api/auth/linear/callback

# backend/.env   — completes it and refreshes tokens
LINEAR_CLIENT_ID=...
LINEAR_CLIENT_SECRET=...
```

Substitute the provider name: `GOOGLE_`, `SLACK_`, `NOTION_`, `HUBSPOT_`,
`GITHUB_`, `LINEAR_`, `SALESFORCE_`, and so on. A handful differ slightly
because the provider's own naming does — Meta/Facebook/Threads use
`*_APP_ID` / `*_APP_SECRET`, X uses `X_CLIENT_ID` / `X_CLIENT_SECRET`, and
QuickBooks uses `INTUIT_*`. If a node's credential screen tells you a variable
is missing, it names the exact one.

Pipedrive's OAuth callback also performs a server-side admin lookup. If you use
that integration, set `SUPABASE_SECRET_KEY` in `frontend/.env` to the same
service-role key used by the backend. It is server-only: never prefix it with
`VITE_`, which would expose it to the browser bundle.

Integrations that authenticate with a plain API key need nothing in your
environment — users paste the key in the UI and it's encrypted with your
`CREDENTIALS_ENCRYPTION_KEY`.

---

## File storage

Uploads, generated images, and workflow resources go to any S3-compatible
bucket:

| Variable                           | Notes                                                                                                                         |
| ---------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `OBJECT_STORAGE_ENDPOINT`          | S3-compatible endpoint. Supabase Storage works: `$SUPABASE_URL/storage/v1/s3`. Cloudflare R2, MinIO, and AWS S3 all work too. |
| `OBJECT_STORAGE_ACCESS_KEY_ID`     |                                                                                                                               |
| `OBJECT_STORAGE_SECRET_ACCESS_KEY` |                                                                                                                               |
| `OBJECT_STORAGE_REGION`            | Optional region; defaults to `us-east-1`.                                                                                     |

Create two **private** buckets named `workflow-resources` and `workflow-cas`.
The first stores uploads/media; the second stores graph snapshots and node
outputs larger than 4 KB. Docker bootstrap creates both automatically. Browser
uploads and downloads use short-lived presigned URLs, so neither bucket should
be made public. Without storage, file/media features fail, execution graph
snapshots cannot be stored, and outputs larger than 4 KB cannot be persisted.

The durable reference is the workflow resource ID, not a presigned URL. NoClick
stores that ID for files uploaded through workflow fields and mints a fresh URL
when the editor displays the file or the workflow executes. SDK/custom-component
code should do the same: persist `resourceId`, then call `resources.getUrl(id)`
immediately before a browser download. Community download URLs expire after 15
minutes by default and must not be saved as permanent links. Deleting the
resource revokes future URL renewal without making either bucket public.

---

## Triggers

**Webhooks and inbound HTTP.** Set `WEBHOOK_URL_BASE` to your backend's public
origin. NoClick then mints webhook URLs as `{WEBHOOK_URL_BASE}/webhook/{webhook_id}`
and serves deliveries there. Your backend must be reachable from the internet for
external services to call it.

**Schedules.** Cron and polling triggers run on an in-process scheduler when
`NOCLICK_LOCAL=1`. It ticks every 15 seconds and fires due schedules — no extra
services. A bare backend launch derives its own loopback scheduler URL and
process-local secret; `CRON_SCHEDULER_URL` and `CRON_SCHEDULER_SECRET` are only
needed to override those defaults. Schedules only run while the single backend
process is running.

**Inbound email.** Disabled and hidden by default. Set `INBOUND_EMAIL_DOMAIN`
on the backend and `VITE_INBOUND_EMAIL_DOMAIN` when building the frontend, plus
`EMAIL_RELAY_SECRET`; configure an email provider for that domain to POST
inbound mail to your backend's `/email/inbound` route. No address is minted
until these values are configured. Outbound workflow notifications and replies
use the operator's Resend account; set `RESEND_API_KEY` and a verified
`FROM_EMAIL`. Inbound triggering still works without those variables, while
outbound sends fail closed.

**Discord app events.** Discord must be able to reach the backend route that
receives registered app-event webhooks. Set `APP_WEBHOOK_BASE_URL` to the
public backend origin (normally the same origin as `WEBHOOK_URL_BASE`). The
Compose and single-origin deployments derive it automatically; set it
explicitly for a manual deployment.

**WhatsApp.** Meta Cloud API credentials work without an instance-wide
provider key. Linking a personal WhatsApp account by QR code uses the external
WAHooks service and requires a WAHooks account plus `WAHOOKS_API_KEY` on the
backend. Without that key, QR linking and QR-backed WhatsApp operations remain
unavailable; other integrations continue to work.

---

## Optional services

| Variable                        | Enables                                                                                                                                                      |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `REDIS_URL`                     | Caching for OAuth state and UI state. Everything works without it, slightly slower.                                                                          |
| `RESEND_API_KEY` + `FROM_EMAIL` | Outbound notification email (run failures, credential alerts, workspace invites). See below.                                                                 |
| `HONEYCOMB_API_KEY`             | OpenTelemetry traces.                                                                                                                                        |
| `POSTHOG_API_KEY`               | Product analytics. Unset means no telemetry is sent — the default.                                                                                           |
| `OUTBOUND_ALLOW_PRIVATE_IPS`    | Set to `1` to let user-configured HTTP, MCP, feed, import, and database connectors reach private/LAN addresses. Off by default to prevent server-side request forgery; only enable on a trusted network with an egress firewall. With the guard enabled, plain MongoDB URIs outside Atlas use one direct host and managed topology is limited to TLS-verified Atlas `*.mongodb.net` hosts; other MongoDB replica/SRV deployments require this opt-out. The old `HTTP_NODE_ALLOW_PRIVATE_IPS` name remains a deprecated alias. |
| `GEOIP_LOOKUP_URL`              | Optional HTTPS URL template containing `{ip}` for country lookup in operator-configured Slack login alerts. Unset means client IPs never leave the instance. |

The Compose `redis` profile runs a pinned Valkey server. Valkey speaks the
Redis protocol, so `REDIS_URL=redis://redis:6379` and existing Redis clients do
not change.

### Notification email

Settings → Notifications lets each user choose which alerts they get — a
workflow failing on a schedule, a credential being auto-revoked, a channel
disconnecting. Nothing sends until the instance has a mail provider, and the
Notifications tab says so when it doesn't.

NoClick sends through [Resend](https://resend.com):

```bash
# backend/.env
RESEND_API_KEY=re_...
FROM_EMAIL=noclick@yourdomain.com   # a domain verified in Resend
```

`FROM_EMAIL` must be on a domain you have verified with Resend, or sends are
rejected. Restart the backend afterwards. Preferences set before configuring
mail are kept — they simply start taking effect.

### Using the SDKs against your instance

Both SDKs default to NoClick's hosted API, so point them at your own backend or
they will talk to the wrong server:

```ts
await init({ apiKey: "nk_live_...", url: "https://noclick.example.com" });
```

```python
sdk = noclick.Client(api_key='nk_live_...', url='https://noclick.example.com')
```

That URL is your **backend**, the same value as the frontend's `VITE_API_URL`.
Create keys under Settings → Developer, where the quick-start snippets are
already filled in with this instance's URL.

---

## What `make local` sets for you

Running `make local` generates and wires everything above for a local install:

- Starts a local Supabase and applies migrations.
- Generates `WORKFLOW_JWT_SECRET`, `CREDENTIALS_ENCRYPTION_KEY`,
  `SESSION_SECRET` and a cron secret into `.noclick/local.env`, reusing them on
  later runs. **Keep that file** — it holds your credential encryption key.
- Points storage at the local Supabase bucket, webhooks at your local backend,
  and the frontend at both.
- Sets `NOCLICK_LOCAL=1`.

Override the ports with `NOCLICK_BACKEND_PORT` and `NOCLICK_FRONTEND_PORT`, and
the state directory (workspaces, volumes, generated secrets) with
`NOCLICK_HOME`.

---

## Differences from NoClick Cloud

Worth knowing before you deploy:

- **Agent turns are one-shot subprocesses**, not retained remote workers. The first turn
  of a conversation is comparable; there's no persistent process between turns.
- **The included AI builder is single-pass.** It builds real workflows, but
  complex graphs may benefit from smaller, iterative requests.
- **Builder input links are bearer capabilities.** They expire, can be used
  once, and should be shared only with the person expected to answer the
  builder's pending questions.
- **No billing, limits, or credits.** Everything is unlimited — your only costs
  are your own model providers and infrastructure.
- **Scheduled maintenance jobs** (nightly trigger reconciliation, digests)
  aren't included; the hosted platform runs those.
- **Publishing interfaces as standalone apps is hosted-only.** The Settings tab
  for that managed publishing service is hidden here. Interfaces still work
  inside the app; expose one publicly through infrastructure you operate.
- **No Billing tab** — there is nothing to bill. Usage still tracks real model
  spend, so you can see what your providers cost you.
- Some hosted conveniences (managed email domains, published-app subdomains)
  need your own equivalent infrastructure.

---

## Troubleshooting

**Login works but the canvas never connects.** The browser's realtime
connection is failing — check `VITE_RELAY_URL` uses `ws://`/`wss://` (not
`http://`) and ends in `/relay`, and that your proxy forwards WebSocket
upgrades.

**"Token verification failed" in the backend log.** The backend and frontend
are pointed at different Supabase projects, or the backend is verifying with
the wrong method. Prefer `SUPABASE_JWK_URL`; the JWT secret only works if your
Supabase signs symmetrically.

**Credentials disappeared after a restart.** `CREDENTIALS_ENCRYPTION_KEY`
changed. Restore the old value — encrypted credentials can't be recovered
without it.

**An agent says it has no tools.** Confirm the integration node is wired into
the agent's _bottom_ handle (the tool handle, not the dataflow input) and that
at least one operation is allowlisted in its config panel.

**Schedules don't fire.** They only run while the backend process is up, and
only when `NOCLICK_LOCAL=1` (otherwise NoClick expects an external scheduler).
