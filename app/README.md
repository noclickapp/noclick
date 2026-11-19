# The app

NoClick's app: the screens for working with a NoClick account, built only on the TypeScript SDK in
[`../sdk/typescript`](../sdk/typescript). It runs with your NoClick key on its server, behind a password only you
know. So far it has your account at a glance, Work, Resources and NoClick's developer console; NoClick's screens
move in here one at a time.

## Configuration

The app reads four environment variables, on its server only. [`.env.example`](.env.example) lists them.

| Variable | What it is |
|---|---|
| `NOCLICK_API_KEY` | The NoClick secret key the app acts with, in your account. Create one in NoClick's developer console. One line of printable characters, with no spaces around it. |
| `APP_PASSWORD` | The password you sign in to this app with. At least 12 characters; make it random (`openssl rand -base64 18`). |
| `SESSION_SECRET` | Signs the sign-in cookie. At least 32 random characters (`openssl rand -base64 48`). |
| `NOCLICK_API_URL` | Optional. The NoClick API to use, if not `https://api.noclick.com`: https, or plain http only on this machine. |

While any of them is missing or unusable, the app serves nothing else: every page shows a setup page (a 503) naming
what to set, the key proxy answers the same as JSON, and nothing is signed in to or sent to NoClick. It names the
variables, never their values.

Changing `APP_PASSWORD` or `SESSION_SECRET` signs everyone out.

## Run it against your NoClick account

You need Node 22.12 or later and pnpm 10 (`corepack enable pnpm` gives you the version `package.json` names).

```bash
cd app
cp .env.example .env        # then fill in your key, a password and a secret
pnpm install --frozen-lockfile
set -a; . ./.env; set +a    # put .env's settings in this shell's environment
pnpm dev                    # a development server on http://localhost:5173
pnpm build && pnpm start    # the production build on port 3000 (PORT changes it)
pnpm typecheck
pnpm test
```

`pnpm start` listens on every network interface unless `HOST` is set: run `HOST=127.0.0.1 pnpm start` to keep it
to this machine. Open the address, sign in with `APP_PASSWORD`, and the first screen reads your account through the
app's own server; **Work** on it opens `/work`, **Resources** `/resources`, and **Developer console** the console at
`/developers`.
`scripts/check.sh` at the
repository's root installs, typechecks, tests and builds the app along with the SDKs, as CI does; the tests need
neither a key nor the network.

To look at the console's pages without touching an account, run `pnpm dev` and open
`http://localhost:5173/developers-lab` (or `/resources-lab` for Resources, `/work-lab` for Work): the same pages over
made-up data. The app still wants its settings and your sign-in first, though the lab calls nothing. See
[the lab](#the-lab).

To deploy it, set the four variables in your host's settings and serve it over **https**: away from `localhost` the
sign-in cookie is `Secure`, so a browser keeps it only over https, and the app tells browsers to come back over
https only (`Strict-Transport-Security`, for a year). A proxy you put in front of the app must pass the original
`Host` header on (with nginx, `proxy_set_header Host $host;`), since signing in checks that the form came from the
app's own address, and should say which scheme it took the request over (`X-Forwarded-Proto`).

## The developer console

`/developers` is NoClick's developer console (`src/screens/console`): the account's agents, users and resources
(connections, numbers, inboxes, apps, databases, storage and the rest), logs of everything that ran, usage and its
caps, and settings. They are the same files NoClick's own app renders; here they run on the SDK client this app
hands every screen, so each call goes through the app's server and is made with its key.

**It isn't finished.** The console starts by reading the account (`GET /v1/account`), which NoClick's API has so
far answered only to a person signed in to NoClick. The change that answers it to one of the account's own secret
keys is still on its way to `api.noclick.com`. Until the API you call has it, `/developers` shows one page saying
that the API refused the key that read, and none of its pages, because without the account a page would say you
lack what it only couldn't read.

**It acts as a key, and a key can't do everything.** NoClick's API keeps a few operations for a person signed in
to NoClick, and refuses them to any key (403 `permission_denied`). The console here doesn't offer what rests on
them; `src/screens/console/ownerOnly.ts` is the one list, read by the sidebar, the search palette and each page:

- **API keys**: listing, making, changing and revoking keys, and the apps connected over MCP. The section isn't
  listed; its address says why, with a link to the same page of NoClick's own console.
- **Signing in the command line** (`noclick login`): approving it is done signed in to NoClick. The page links
  there, keeping the code.
- **The setup prompt for a coding agent**, which carries a one-time code that becomes a key. Quickstart shows the
  steps to do by hand.
- **The account's defaults** (its region, what a paused user is told): read here, changed in NoClick's console.
- **Jumping to an object by pasting its id** in the search palette. Sections and recent objects still work.
- **Asking for machines**, and **the card issuer's form**: where the request or application stands is shown, with
  who can go on with it and a link to where they do.
- **Revealing a card's number**: it needs the `cards:reveal` scope, which a key with every scope (`*`) doesn't hold.

The same list holds what Work leaves out for a key (see [Work](#work)).

A key's own limits apply as well: give the app a key with the scopes its pages need, and a spending cap.

**What else differs from NoClick's own console**, because it comes from NoClick's app and not from the API:

- Live where the API offers the account's change stream (see [Live updates](#live-updates)): a resource that moved is
  read again. Without it, lists refresh when you return to the tab and on their own slow re-read.
- A connection is drawn with a plain mark and a name read from its type, not its service's logo.
- Links to the docs, pricing, adding funds and the usage policies open `noclick.com`.
- No terms are named under the buttons: say your own through a slot (below).

### Slots, and your own additions

A screen leaves named places for whoever runs it: **slots** (`src/slots.ts`). Each has something that stands in it
by default, so the app is whole with every slot left alone. The console's are in `src/screens/console/slots.ts`:

| Slot | Where it is | By default |
|---|---|---|
| `console.terms` | Under a button that makes a key, approves a command line's sign-in or copies the setup prompt | Nothing |
| `console.cards.issuerForm` | The cards onboarding page, for the signed-in owner | A link to where the application is finished |

One is drawn by several screens, so it is in `src/ui/slots.ts`:

| Slot | Where it is | By default |
|---|---|---|
| `connection.mark` | Beside a connection's, an account's or an integration's name, in the console and in Work: its mark, what it is called, the AI company an AI account is with, and how an account reads in a list (its app and the line telling it apart) | A plain mark, the name read from its type, no company, and an account by the account it reaches, else its own name, else when it was connected |

Resources' (`src/screens/resources/slots.ts`; see [Resources](#resources)):

| Slot | Where it is | By default |
|---|---|---|
| `resources.kinds` | Around the page: kinds, or items of a kind, the host adds, with what draws them | Nothing |
| `resources.numbers` | Around the page: the account's phone numbers, each with what it costs a month, and how one is bought | The API's phone numbers, at their own monthly price, bought through the API |
| `resources.number.actions` | A number's page, beside its facts | Nothing |
| `resources.file.markdown` | A Markdown file's preview | Its text drawn as a repository's README is |

The channels' (`src/screens/channels/slots.ts`; Work draws them):

| Slot | Where it is | By default |
|---|---|---|
| `channels.agent.face` | An agent's face, wherever a channel draws one | Its initials on its own colour |

Work's are listed under [Work](#work).

Fill one from a file in [`src/custom/`](src/custom/README.md), which is where everything your copy adds goes: every
file there runs before any page renders, and nothing else in the app imports from it, so pulling a newer version
of the app leaves your additions alone. Its README has a worked example.

### The lab

`/developers-lab` is the console over made-up data (`src/screens/console/fixtures`): the real pages and the real SDK
client, answered from canned `/v1` responses, with no account and no network. It exists **in development only**
(`pnpm dev`); a built app answers 404 there and carries none of it.

- `?fixture=populated|empty|first-run|error` picks the data, and sticks as you move around.
- `?as=key` answers as the API answers a key, which is the console as this app serves it; without it the lab shows
  what a signed-in owner sees.
- It also draws what is designed and not built yet, each tagged "designed". The console at `/developers` never
  shows those.

`/work-lab` is Work over its own made-up data (`src/screens/work/fixtures`), likewise in development only: `?scene=`
picks a view (its index lists them all), and `?as=key` answers as the API answers a key.

## Resources

`/resources` is what the account owns and what it costs (`src/screens/resources`): its phone numbers, domains, email
addresses, websites, databases, storage, code, and what its workflows keep (their files and tables) beside its own
files. The overview is one tile per kind; a kind lists its items with their prices; an item opens its own page, with
what it is, what uses it, and the thing itself (a repo's files, a domain's records, a database's tables, a file's
preview). It is the same page NoClick's own app draws, reading through the client the app hands every screen, so it
acts as the app's key: what only the owner may do is left out as in the console (`ownerOnly.ts`), and
`src/screens/resources/resourcesAsKey.test.tsx` opens every page of it as a key and fails if one asks for that.

What differs from NoClick's own Resources:

- No agents, skills, memories, machines or secrets among its kinds: NoClick's app adds those from its Work pages
  through `resources.kinds`; here they are on [Work](#work)'s own pages.
- No agents' workspaces among the files: an agent made on a workflow's canvas keeps its files where only NoClick's
  app reads them, so they appear there alone.
- Every workflow the key reads is listed, not one workspace's.
- A workflow is named, not opened: this app has no canvas.
- No "Ask NoClick", and nothing goes to a command palette.

## Work

`/work` is where the account's people and agents work (`src/screens/work`): its spaces, each with its channels,
direct messages and threads, its people and agents and what they may reach; the account's agents, each with its
conversation, triggers, tools, files and activity; making an agent; and machines, with their disk, settings and a
shell. It is the same page NoClick's own app draws, reading through the client the app hands every screen, so it
acts as the app's key.

**What it leaves out for a key**, from the same list as the console (`ownerOnly.ts`):

- **Spaces the owner joined in other accounts**: a key is the account, not the person who joined them.
- **Opening the personal space to people.**
- **Asking for machines** and accepting their usage policy.
- **Approving or declining a call NoClick holds for the owner's yes**: its card links to NoClick's page for it.

Anything else is offered, and the key's scopes decide: what a scope the key lacks would allow, the API refuses, and
Work says so in the API's words where you tried. An agent's sandbox (its files, the `@` files in its box, a shell on it)
is one: it needs the `agents:terminal` scope, which the account's key with every scope (`*`) doesn't hold, so give the
app a key with that scope only if its password should carry it.

`src/screens/work/workAsKey.test.tsx` opens every view of Work over its fixtures as the owner and as a key, fails if
the key's views ask for anything the API refuses every key, and keeps every call either makes in `workCalls.txt`.

**Everyone who has the password can do whatever the app's key allows.** Work acts with the key, and NoClick's API lets
an account's key do all of this, so anyone signed in here can:

- read every channel, direct message and thread the account is in, and every conversation of its agents, and post in
  them as you;
- answer the questions the account's agents ask;
- invite people to a space (the invitation says it is from you), change their roles and remove them;
- archive a space and put it in the trash;
- share the account's connections, databases, apps and machines with a space, at a level;
- make, change, message and delete agents, including agents that run commands in sandboxes of their own;
- buy machines once the account may, and spend whatever else the key's scopes and spending cap allow;
- drive an agent's browser from its live view;
- with `agents:terminal`, read an agent's sandbox and open a shell on it.

What stays yours, on NoClick's own pages, signed in or from the link NoClick sends you: approving a call held for your
yes, raising the account's spending cap, adding funds, linking a phone, and what the console's list above names. The
key's scopes are how you choose the rest: start with none that spend and without `agents:terminal`, widen them only
knowingly, and give the key a spending cap. Use a long random password, and share it only with people you would hand
what the key allows. Signing out drops this browser's copy of Work's channels and threads.

What differs from NoClick's own Work:

- Who is typing is named as the channel's members name them: the change stream says who by id alone.
- No cards under an agent's turns (a purchase held for a yes, an account to connect, a build on its canvas): each
  call is a row of the turn's steps.
- No "Ask NoClick", no search palette, and no opening a workflow's step: this app has no chat with NoClick and no
  canvas.
- Connecting an app's account or an AI account opens NoClick's connect page in a new tab, and Work waits for the
  account to land. A tool server (MCP) that asks you to sign in is added on NoClick, or with its key.
- Adding funds opens NoClick's page for it, and the account's connections open NoClick's. Resources opens this app's.
- An app is drawn with a plain mark and the name read from its type; a coding harness the app has no drawing of
  (OpenCode, Hermes, OpenClaw) with a plain dot.
- Only the account's own agents are listed: NoClick's app also lists those of the account's platform users.

Its slots (`src/screens/work/slots.ts`), besides `connection.mark` and the channels':

| Slot | Where it is | By default |
|---|---|---|
| `work.turn.cards` | Under an agent's turn: a card for what a call did | Nothing: each call is a row of the turn's steps |
| `work.reply.markdown` | A reply's, a question's or a browser's found text | Drawn as a repository's README is |
| `work.message.file` | A file a texted or emailed message carried | A link that opens it |
| `work.model.name` | A model's name as people read it | Its id |
| `work.apps` | The apps an agent can use as tools, and whose an account is | The integrations the API lists |
| `work.connect.app` | Connecting an app's account where it's needed | NoClick's connect page in a new tab |
| `work.connect.model` | Connecting the AI account a model needs | NoClick's connect page in a new tab |
| `work.toolServer.signIn` | Signing in to a tool server added as an agent's tool | Says to add it on NoClick, or give its key |
| `work.funds.add` | Adding funds, where a costly model needs them | A link to NoClick's page for it |
| `work.harness.mark` | The marks of coding harnesses the app has no drawing of | None: a plain dot |
| `work.file.preview` | An agent's workspace file, previewed | A picture, a recording or text at the link the API signed |
| `work.address` | Where Work is, for its pieces drawn elsewhere | This app's `/work` |
| `work.joinedSpace.typing` | Saying you're typing in a space you joined in another account | Through the API, as in your own spaces |

## Live updates

Every page follows the account's change stream (`watch` in the SDK) where NoClick's API offers it
(`src/sdk/watchLive.ts`): one stream for the whole app, opened when a page follows it and closed half a minute after
none does. Each change names an object and the page reads that object again; a change it can't name, or a stream that
reopened without carrying on from where it was, has the page read everything it shows again. While the stream isn't
live (opening, reconnecting, or refused because the API you call doesn't offer it yet), Work reads what it shows again
when you come back to the tab and every minute while the page is shown, and the stream is asked for again every five
minutes, so it turns on by itself once the API offers it. The console and Resources read again their own way meanwhile.
An agent's open conversation is live through its own stream either way.

## How it reaches NoClick

- **The key stays on the server.** The browser's SDK client calls the app's own `/api`, and the key proxy
  (`src/server/proxy.server.ts`, at `/api/v1/*`) sends each call on to NoClick's `/v1/*` with `Authorization: Bearer`
  and the app's key.
  - It forwards only calls from the app's own SDK client, which sends `Authorization: Bearer held-by-this-app-server`
    (a placeholder, not a secret). A link, an embed or a page opened at an API address can't send that, so none of
    them reaches NoClick, and no API answer is ever shown as a page.
  - It passes on only the headers the SDK sets (`Accept`, `Content-Type`, `Idempotency-Key`, `NoClick-User`), never
    the browser's cookies or `Authorization`, and only paths under `/v1/` (it refuses `..`, empty segments and their
    encoded forms).
  - It passes back only the response headers it lists: the ones the SDK reads (`x-request-id` and the edge's
    `cf-ray`, `retry-after`, `idempotent-replayed`) and the ones a body or a download needs (`content-type`,
    `content-disposition`, `content-language`, `content-range`, `accept-ranges`, `etag`, `last-modified`), with a
    redirect's `location` rewritten. Anything else NoClick's API sends (its cookies, connection headers, and policies
    or reporting meant for its own origin, such as `report-to` or `clear-site-data`) stays on the server. Nothing is
    stored or compressed on the way.
  - Bodies stream both ways, so server-sent events (an agent's `watch`) arrive as they happen, and a browser going
    away ends the call to NoClick.
- **Screens take their client from `useClient()`** (`src/sdk/client.tsx`). The root route hands them one for this
  app's `/api` (`src/sdk/proxied.ts`); another app hosting these screens can hand them its own. Server code that needs
  NoClick before a page renders uses `serverClient()` (`src/server/client.server.ts`), and passes it as `{ client }`
  to every SDK call: the SDK's default client would read `NOCLICK_API_KEY` by itself.
- **Few modules hold a secret.** `src/server/config.server.ts` alone reads the environment; only the proxy and the
  server client read the key, and only the gate, sign-in and the session read the password and session secret. Every
  one is a `.server` module, which the build refuses to put in the browser's bundle. `test/secrets.test.ts` guards
  against an accidental change to any of that, by name: it is a check on mistakes, not a proof, and code set on
  getting around it (a name built at run time, a value passed along) gets past it.
- **WebSockets don't go through the proxy.** It forwards HTTP, including streams of events, but not a WebSocket. A
  machine's shell, a browser's live view and the change stream open theirs at NoClick's API directly, with a
  single-use token the app asks for through the proxy (sent as the socket's first message, or offered beside its
  protocol, never in its URL), so the key never reaches the browser. The SDK opens each; no screen opens one itself.

## What the sign-in protects, and what it doesn't

It protects:

- **Pages, data and the key proxy.** Every request React Router answers passes a gate (`src/server/gate.server.ts`)
  first: the root route's middleware for every request to a route, and the server entry (`src/entry.server.tsx`) for
  the few React Router answers without middleware (a method no route takes, a path no route matches). Without a
  session, a page sends you to `/login`, and back afterwards to where you were going, if that is a path on this site;
  an API path answers 401 without calling NoClick.
- **The session cookie.** It is `HttpOnly`, `SameSite=Lax`, signed with a key derived from `SESSION_SECRET` and
  `APP_PASSWORD`, and `Secure` with a `__Host-` name everywhere but a browser on the same machine. It holds only when
  you signed in, and lasts 7 days from then, checked on the server; it isn't renewed.
- **Requests from other sites.** Signing in, signing out and every call to the key proxy, reads included, are refused
  when the browser says another site sent them (`Sec-Fetch-Site`, or in older browsers an `Origin` that isn't the
  app's own, scheme and port included).
- **Framing and sniffing.** Every answer that passes the gate, the setup page and the app's error pages included,
  says it may not be shown inside another site's page, may not be read as another type, and may not be stored.
- **Guessing, a little.** A wrong password is answered only after a second, and each copy of the server checks at
  most three passwords at once, turning further attempts away unchecked. One copy answers at most about three wrong
  guesses a second, however many requests arrive together.

It doesn't:

- **Keep you signed in while someone floods sign-in.** Three attempts a second keep every check busy, and then your
  own correct password is refused, not delayed, for as long as they keep it up. A session you already have keeps
  working, but sessions aren't renewed, so after seven days of it you are locked out. Nothing on a stateless server
  fixes this; rate limiting sign-in at your host or in a proxy in front of the app does.
- **Stop guessing for good.** Nothing is stored, so nothing remembers failed attempts or locks anyone out. A host
  running several copies of the server allows that many times the guesses. A long random password is what makes
  guessing hopeless; the delay only slows it.
- **End a session everywhere.** Signing out removes the cookie from that browser. A copy of the cookie works until it
  expires. To end every session at once, change `SESSION_SECRET` or `APP_PASSWORD`.
- **Tell people apart.** There is one password and one owner. Anyone who has it acts with the app's key, with
  everything that key may do in your account. Give the app a key with only the scopes and spending cap it needs.
- **See every request.** The production server answers a few before the gate, with nothing of the app's in them: its
  static files (the public scripts and styles); React Router's route manifest (`/__manifest`, the app's routes and
  module names, the same for everyone); and requests the Node server refuses outright, with a bare error page (a URL
  whose percent-encoding doesn't decode, 400; `TRACE`, a missing or broken `Host`, `OPTIONS *`, 500). Those error
  pages carry no framing header, and have nothing on them to click. `test/served.test.ts` pins every one.
- **Protect a copy served over plain http** away from your own machine: the browser won't keep the sign-in, and
  anything on the network can read what you type.

## How it is put together

- React Router 7 in framework mode, with Vite, middleware turned on. `src/` is the app directory: `root.tsx` is the
  document and the root route, `entry.server.tsx` renders documents on the server, `routes.ts` is the route table,
  `routes/` the pages and resource routes, `server/` the server-only modules (sign-in, the gate, the key proxy),
  `sdk/` the client the screens use and how they read through it, `screens/` the screens, `ui/` the design tokens
  and components, `slots.ts` the places a screen leaves for its host, and `custom/` your own additions.
- The theme (light, dark or the system's) is the one a person picks in the console's account menu, kept in the
  browser and applied before the first paint (`src/ui/theme.ts`). Dark is the default.
- Server code uses web standards only (`Request`, `Response`, `fetch`, Web Crypto, web streams), so it runs on Node
  today and on runtimes that offer only those.
- `@/…` imports from `src/…`.
- `noclick` is the SDK's source in `../sdk/typescript/src`, not the package from npm, so the app always runs on the SDK
  as this repository has it, with no build step between them.
- Tailwind CSS 3, with the theme in `tailwind.preset.ts` and the tokens in `src/ui/tokens.css`.
- `test/imports.test.ts` keeps the app buildable from this repository alone: no file imports a path outside it, and
  every package a file imports is one `package.json` names. `test/server.test.ts` runs the app's server through React
  Router's own request handler against a fake NoClick API on a local port; `test/served.test.ts` builds the app and
  runs it under `react-router-serve`, as `pnpm start` does.
- `test/sockets.test.ts` keeps every screen on the SDK client it is handed: none opens a connection of its own.
  `test/slots.test.ts` keeps each slot declared once, beside its screen. `src/screens/console/consoleAsKey.test.tsx`
  opens every page of the console as a key and fails if one asks the API for something only the owner may have;
  `src/screens/resources/resourcesAsKey.test.tsx` does the same for Resources, and
  `src/screens/work/workAsKey.test.tsx` for Work.

Apache-2.0, as the rest of this repository.
