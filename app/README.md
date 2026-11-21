# The app

NoClick's app: the screens for working with a NoClick account, built only on the TypeScript SDK in
[`../sdk/typescript`](../sdk/typescript). It runs with your NoClick key on its server, behind a password only you
know. So far it has your account at a glance, the chat, Work, Connections, Resources and NoClick's developer console; NoClick's
screens move in here one at a time.

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
app's own server. It sits in the app's frame, as `/chat`, `/work`, `/connections`, `/resources`, `/settings` and `/usage` do: a sidebar on a laptop (the
pages, search, and your account with its menu), a bar with the page's name and a menu on a phone, and ⌘K to go
anywhere (see [The frame](#the-frame)). **Developers** in the account menu opens the console at `/developers`.
`scripts/check.sh` at the
repository's root installs, typechecks, tests and builds the app along with the SDKs, as CI does; the tests need
neither a key nor the network.

To look at the console's pages without touching an account, run `pnpm dev` and open
`http://localhost:5173/developers-lab` (or `/resources-lab` for Resources, `/work-lab` for Work, `/chat-lab` for
Chat, `/connections-lab` for Connections, `/usage-lab` for Usage, `/settings-lab` for Settings): the same pages over
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

Some are drawn by several screens, so they are in `src/ui/slots.ts`:

| Slot | Where it is | By default |
|---|---|---|
| `connection.mark` | Beside a connection's, an account's or an integration's name, in the console and in Work: its mark, what it is called, the AI company an AI account is with, and how an account reads in a list (its app and the line telling it apart) | A plain mark, the name read from its type, no company, and an account by the account it reaches, else its own name, else when it was connected |
| `connect.app` | Connecting an app's account where it's needed (an agent's tools, a trigger's account, a workflow step's account pickers, in place under them), and entering an account's values again, with the client of the screen drawing it. Its dialog hands back what lands by both its names: the ref an agent names it by (an account connected in the app's `credential:<id>`, a named connection's name), which an agent's tools are saved with, and the id of the account it holds | NoClick's connect page in a new tab, for a named connection, where an account is also connected again: nothing here takes an account's values |
| `connect.model` | Connecting the AI account a model needs, from the model picker or an agent step's account pickers, handing back what lands by the same two names: the model picker picks its ref, the step keeps the account it holds | NoClick's connect page in a new tab, for a named connection |

Resources' (`src/screens/resources/slots.ts`; see [Resources](#resources)):

| Slot | Where it is | By default |
|---|---|---|
| `resources.kinds` | Around the page: items the host adds to the kinds Resources lists, with what draws them | Nothing |
| `resources.numbers` | Around the page: the account's phone numbers, each with what it costs a month, and how one is bought | The API's phone numbers, at their own monthly price, bought through the API |
| `resources.number.actions` | A number's page, beside its facts | Nothing |
| `resources.file.markdown` | A Markdown file's preview | Its text drawn as a repository's README is |

The channels' (`src/screens/channels/slots.ts`; Work draws them):

| Slot | Where it is | By default |
|---|---|---|
| `channels.agent.face` | An agent's face, wherever a channel draws one | Its initials on its own colour |

The Usage page's (`src/screens/usage/slots.ts`): the money behind it is the deployment's, so a host that bills fills
them, and without one the page shows what each thing cost:

| Slot | Where it is | By default |
|---|---|---|
| `usage.billing.planLine` | Under the page's title, where the deployment bills | Nothing: the title says what the page shows |
| `usage.billing.balance` | Beside the headline, where the deployment bills | The balance as read, with a link to add funds on NoClick |
| `usage.billing.alert` | Above the headline: money owed, work paused, money running out | Nothing |
| `usage.charge.price` | A charge's facts: how it was priced | Nothing |
| `usage.charge.run` | The run a charge belonged to, opened from its facts | What the charges read says of it, with its automation on NoClick |
| `usage.charge.ask` | A charge's facts: asking about it | Nobody, and no button |

Settings' (`src/screens/settings/slots.ts`): every section's body is a slot. Where the app has a section of its own it
stands there, and a host fills it only to draw its own; a section whose body is only the deployment's has nothing
there, and Settings doesn't list it:

| Slot | Where it is | By default |
|---|---|---|
| `settings.usage` | Usage: what each thing cost | The Usage page |
| `settings.workstreams` | Workstreams: the lines of work spend is counted under | Each workstream with what it spent this month, renamed and archived through the API |
| `settings.billing` | Plan and billing: the plan, adding money, the spending cap | The plan and balance as read, with NoClick's pages for them, and the cap (a key lowers it) |
| `settings.notifications` | Notifications: the email alerts sent to the owner | Each alert with its switch |
| `settings.developer` | Developer: the way into the developer console | The console's row, at its address |
| `settings.members` | Members: who's in the workspace and how they sign in | Nothing, and no section |
| `settings.phone` | Phone: the numbers the account's owner messages and calls NoClick from | The app's own, linked by a code (listed only where the page acts as the owner) |
| `settings.skills` | Skills: the skills NoClick's builder loads for the account | The app's own, through `/v1/builder_skills` |
| `settings.skills.editor` | Skills: the editor a skill opens in | Its words (name, description, text) |
| `settings.skills.share` | Skills: sharing one of the account's skills | Nothing, and no Share button |
| `settings.popups` | Popups: which of the app's popups and banners appear | The app's own |
| `settings.developer.olderKeys` | Developer, under the console's row: keys made before the console | Nothing |

The app shell's (`src/screens/shell/slots.ts`): the frame and sidebar a page sits in (see [The frame](#the-frame)).
A host fills what it keeps in its sidebar and menu:

| Slot | Where it is | By default |
|---|---|---|
| `shell.pages` | The pages the sidebar lists | The pages this app serves: Chat, Work, Connections and Resources |
| `shell.workspace` | Atop the sidebar, beside search | The account's name |
| `shell.foot.card` | The sidebar's foot, while it's open | Nothing |
| `shell.foot.balance` | The sidebar's foot, kept mounted on the rail | Nothing |
| `shell.foot.invite` | The sidebar's foot, under the balance | Nothing |
| `shell.account.session` | The account's plan, and signing out | The plan the API names; signing out of this app |
| `shell.account.switchTo` | First in the account menu | This app's developer console |
| `shell.account.billing` | The account menu's billing rows | Usage: this app's `/usage` |
| `shell.account.items` | The account menu, above Community | Send feedback: a note to the NoClick team (`POST /v1/feedback`) |
| `shell.account.staff` | The account menu's last rows | Nothing |
| `shell.account.around` | Around the account row (what opens over it) | The feedback dialog that row opens |
| `shell.banner` | A strip across the top of the page | Nothing |
| `shell.palette` | The ⌘K palette's commands, the sections "Open …" narrows to and the shortcuts it lists | The pages this app serves and Resources' kinds, what its pages handed over, the theme, the shortcuts and signing out |

The workflow canvas's (`src/screens/canvas/slots.ts`): the canvas isn't one of this app's pages yet, and these are the
parts of it only a host has. Connecting the account a step or an agent needs is the shared `connect.app` and
`connect.model`. What's heavy in a default (the SDK, the plain step's drawing) loads the first time it's used, so a host
that fills a slot never downloads it: whatever reads one of these imports them all.

| Slot | Where it is | By default |
|---|---|---|
| `canvas.builder` | Beside the canvas (over it on a phone): building the workflow by asking for it | A build of the open workflow (`Workflow.build`), its question answered on NoClick, then what it did |
| `canvas.presence` | Other people editing it live: their pointers, selections and unsaved moves | Nobody else: others' changes arrive once they're saved |
| `canvas.interface` | The Interface tab: the workflow's forms, tables and chats as a page | A note that it's laid out and published on NoClick, with the workflow's link there |
| `canvas.agentChat` | An agent step's chat, a block of the Interface tab | A note that the agent is talked to on NoClick, with the link |
| `canvas.share` | Sharing the workflow with people, from its top bar | A dialog that sends you to share it on NoClick |
| `canvas.graph.saves` | How the workflow's graph is saved and read again, beyond `/v1` (asked by the graph store, `graph/liveGraphStore.ts`) | Every save as the edits that changed it (`POST /v1/workflows/{id}/edits`), the graph read from `/v1` |
| `canvas.step.drawing` | How each step type is drawn (`nodes/lazyNodeTypes.tsx`), and what it draws as before its node loads | A sticky note as a note; any other step as a plain step (`nodes/PlainStep.tsx`): its card, the catalog's glyph where the host loaded it, and a handle for each connection it holds; both loaded with the first step drawn, every step its outline until then |
| `canvas.step.roles` | What a step is by its type, for its node, handles and hints: a trigger, an agent's tool, an older type's new name | What `GET /v1/step_types/{type}` says, read once a session and drawn again as each lands |
| `canvas.step.editing` | Which steps a build is working on, to open their cards while it lands | None known: a build the canvas follows marks the steps it adds in their data, which opens them all the same |
| `canvas.note.markdown` | A sticky note's text, drawn from its Markdown | Drawn as a code repository's README is |

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
picks a view (its index lists them all), and `?as=key` answers as the API answers a key. `/chat-lab` is the same for
the chat (`src/screens/chat/fixtures`, `src/screens/chat/lab`), and `/connections-lab` for Connections
(`src/screens/connections/fixtures`, `src/screens/connections/lab`).

## Resources

`/resources` is what the account owns and what it costs (`src/screens/resources`): its agents, phone numbers, domains,
email addresses, websites, databases, storage, skills, memories, machines, secrets, code, and what its workflows keep
(their files and tables) beside its own files. Agents, skills, memories, machines and secrets are drawn by
[Work](#work)'s own parts, so each reads and acts as it does in a space's Resources tab, and an agent's page opens it
in Work. The overview is one tile per kind; a kind lists its items with their prices; an item opens its own page, with
what it is, what uses it, and the thing itself (a repo's files, a domain's records, a database's tables, a file's
preview). It is the same page NoClick's own app draws, reading through the client the app hands every screen, so it
acts as the app's key: what only the owner may do is left out as in the console (`ownerOnly.ts`), and
`src/screens/resources/resourcesAsKey.test.tsx` opens every page of it as a key and fails if one asks for that.

What differs from NoClick's own Resources:

- No agents' workspaces among the files: an agent made on a workflow's canvas keeps its files where only NoClick's
  app reads them, so they appear there alone.
- Every workflow the key reads is listed, not one workspace's.
- A workflow is named, not opened: this app has no canvas.
- "Ask NoClick" drafts the message in this app's chat, and the ⌘K palette opens any item the page listed, from any
  page of the frame.

## Usage

`/usage` is what each thing cost, as it was used (`src/screens/usage`), opened from Usage in the account menu: what the
billing period will come to at this pace, each day by service, where the money went (by service, automation, agent,
site or person, and inside each), what's coming up, and every charge, a page at a time, with its own facts. It reads
the account's ledger (`Usage.ledger`, `Usage.billing` and `Usage.charges` in the SDK): every charge the account was
billed in its billing period, its automations' runs and its chat with NoClick included, not only its keys' calls. It is
the same page NoClick's own app draws in Settings, and it acts as the app's key: a key reads the money behind it
without auto top-up or friends' credit, so the balance shows as read, with NoClick's page for adding funds, and where
the balance runs out at this pace the headline says so, never that work stops: a refill isn't a key's to know of.
`src/screens/usage/usageAsKey.test.tsx` opens every scene of its lab as a key and fails if one asks for what only the
owner may have. `/usage-lab` is the page over made-up accounts (`src/screens/usage/fixtures.ts`, `src/screens/usage/lab`)
in development only: `?scene=` picks a view, and `?as=key` answers as the API answers a key.

## Settings

`/settings` is Settings (`src/screens/settings`), in the sidebar: Usage, the page above; Plan and billing, the plan
and the balance as the account reads them (`GET /v1/account`), with NoClick's pages for changing the plan and adding
funds, and the monthly spending cap with what its period spent (`Usage.limits` and `Usage.setAccountCap` in the SDK);
Notifications, the email alerts NoClick sends the account's owner, one switch each (`Notifications.get` and
`Notifications.update`); Popups, which of the app's popups and banners appear, one switch each (`Popups.get` and
`Popups.update`); and Developer, the way into the console at `/developers`. It acts as the app's key: a key lowers the
cap, or sets one where there's none, and raising or removing it opens NoClick's own Plan and billing (the owner's,
`src/screens/console/ownerOnly.ts`). Phone, the numbers linked to the account (`AccountPhones`), is listed only where
the page acts as the owner: a linked number signs in to the account, so a key links one only with the `account:phones`
scope, which this app's key doesn't carry. What only a deployment has (its people, its builder's skills) is a slot no
section stands in, so Settings doesn't list it. Its section is the address's `?section=`.
`src/screens/settings/settingsAsKey.test.tsx` opens every scene of its lab as the owner and as a key and fails if a
key's asks for what only the owner may have, or is refused, or if any call sends or reads a secret; `/settings-lab` is the page over a made-up
account (`src/screens/settings/lab`) in development only: `?scene=` picks a view, and `?as=key` answers as the API
answers a key.

## Chat

`/chat` is the account's NoClick to talk to (`src/screens/chat`): its one session with the account, live, every turn's
work drawn as Work draws an agent's, messages that came by text, email or a call captioned with the app they came by,
NoClick's own notes folded into what it handled, and the files it made. Its box is Work's (files, references to
automations and accounts, `/loop`, `/clear` and `/resume`, Stop and Steer) with NoClick's model, the account its model
runs on, where it runs and its budget beside it. Beside the conversation is what NoClick's helpers are at and what
needs you, a helper's own conversation opening beside the chat. Under a turn, its cards: a held purchase with what it
costs, long work followed to its end, a build on its automation's preview, agents and channels (answered in place), a
placed call followed live, an MCP server with each client's steps, an agent's question to you, a hand-off's receipt,
a served domain, links to connect an account or to pay. The memories panel reads, edits and forgets what NoClick
remembers. Connect lists the other ways into the same conversation: NoClick's WhatsApp and iMessage numbers, its email
address, and the setup guides for using NoClick from an MCP client. "Ask NoClick" from Work and Resources lands here as
a draft. It is the same page NoClick's own app draws, reading through the client the app hands every screen, so it
acts as the app's key.

**Everyone who has the password talks to NoClick as you.** The chat acts with the key, and NoClick's API lets an
account's key do all of this, so anyone signed in here can:

- read your whole conversation with NoClick, the texts, emails and calls in it included, its quiet background
  conversation, and every memory it keeps (the memories panel says so);
- send it messages, which it acts on with the key's power;
- answer the questions other agents asked you;
- change NoClick's model, the account it runs on, its harness and its budget.

What stays yours, on NoClick's own pages, signed in or from the link NoClick sends you:

- **Approving a held purchase or deletion**: its card, and the Beside's Review, open its page on NoClick.
- **Raising the account's spending cap and adding funds**: the out-of-funds card and a paused agent's ask link to them.
- **Linking a phone**: a text from a phone that isn't linked starts an account of its own, so the Connect menu offers
  NoClick's numbers to text only once your phone is linked, and otherwise links to Settings on NoClick.
- **Claiming or renaming NoClick's email address**: ask NoClick, which can. Its mail can be switched on or off here.

The page never tells NoClick you're watching it: you are still texted what it would text you, since whoever reads the
chat here may not be you.

What differs from NoClick's own Chat:

- A build's question is shown with a link to answer it on NoClick's page for it, until the builder's questions become
  ordinary questions this app answers through the API.
- An agent's question about your own accounts (a repository, a team) is answered in words, not picked from a list.
- Connecting an account, or signing in with an AI plan, opens its page on NoClick in a new tab; the card says when it
  has connected.
- A build or an agent is drawn on a preview of its automation, not the interactive canvas; "Open canvas" opens it on
  NoClick.
- A link to pay (funds, a plan, a phone number's purchase page) opens its page on NoClick.
- No finishing an automation set up on another page, and none of the cards NoClick's old chat drew before it moved onto
  the API: those calls are rows of their turn's steps.
- Integrations are drawn with plain marks.

`src/screens/chat/chatAsKey.test.tsx` opens every scene of the chat's lab as the owner and as a key, fails if the key's
views ask for anything the API refuses every key, and keeps every call either makes in `chatCalls.txt`.

Its slots (`src/screens/chat/slots.ts`), besides Work's `work.reply.markdown` and `work.message.file`, the shared
`connection.mark`, `mcp.client.marks` and the channels':

| Slot | Where it is | By default |
|---|---|---|
| `chat.cards.more` | Under a turn: cards of the host's own, for its own tools or what a call answered | None beyond the chat's own |
| `chat.working` | The mark a build at work wears in its card | A live dot |
| `chat.build.question` | The question a build waits on, under its card | Says what it asks; answered on NoClick's page |
| `chat.question.pick` | An agent's question about your own accounts | Answered in words |
| `chat.note.setup` | The card under a note setting up an automation | Nothing: the note's words stand |
| `chat.outOfFunds` | Under a reply turned down for want of funds | A link to adding funds on NoClick |
| `chat.connect.link` | Connecting an account a card asks for | Its page on NoClick in a new tab, then "connected" |
| `chat.approval` | Reviewing held calls from the Beside | None: each opens its page on NoClick |
| `chat.connect.text` | The Connect menu's WhatsApp and iMessage | NoClick's numbers, once your phone is linked |
| `chat.connect.email` | The Connect menu's email | NoClick's inbox, its mail switched on or off |
| `chat.places` | Where a card's links go (Resources, an automation's canvas) | This app's `/resources`; the canvas on NoClick |

## Connections

`/connections` is the apps and accounts your agents and automations act through (`src/screens/connections`): every app
and AI company in one grid, the popular ones first, each a button away from connecting another account; your accounts
(Connected, and Shared with me), the broken ones first; and an account's own page, with proof it works in its
provider's own words (your channels, your repositories, who it signs in as, or its refusal), the automations that use
it, who it's shared by, and Rename, Reconnect and Delete (which names what still uses it first). Below the catalog,
the setup guides for using NoClick itself from an MCP client. It reads the accounts the platform API lists: those
connected in NoClick's app and the named connections code made.

**No secret passes through this app.** Connecting an app or an AI account makes a named connection (its name made up,
such as `gmail-lq2x`) and opens its connect page on NoClick in a new tab, where the account is signed in to or its key
typed; the page lists it once it lands. Reconnecting opens the account's own connect link the same way, so an account
connected in NoClick's app is connected again in place. A check asks the provider through NoClick, at most 20 a minute
an account, once a session when an account's page first opens.

What stays yours, on NoClick's own pages, signed in:

- **Choosing who else may use an account**, and taking one shared with you off your list: the API doesn't share
  accounts, so the Access section says whose it is and links to the account on NoClick.
- **Lifting an account's approvals**: the API only adds them, so Approvals opens its page on NoClick.

What differs from NoClick's own Connections:

- There is no Workspace tab: this app reads the account's own workspace.
- The catalog is the integrations the API lists, each AI provider its own tile, drawn with plain marks.
- Environment variables and MCP servers' keys aren't listed: the API doesn't list them as connections.
- No WhatsApp number's agent on its page.

`src/screens/connections/connectionsAsKey.test.tsx` opens every scene of its lab as the owner and as a key, fails if
the key's views ask for anything the API refuses every key, keeps every call either makes in `connectionsCalls.txt`,
and holds that connecting an app sends no secret.

Its slots (`src/screens/connections/slots.ts`), besides the shared `connection.mark`, `connect.app`, `connect.model` and
`mcp.client.marks`:

| Slot | Where it is | By default |
|---|---|---|
| `connections.reads` | Around the page: the accounts it lists | Every connection the API lists in the workspace the page shows |
| `connections.apps` | The apps the catalog lists and accounts are matched to | The integrations the API lists |
| `connections.connect` | Connecting another account of an app from the catalog | NoClick's connect page in a new tab |
| `connections.ai` | The AI companies in the catalog, and connecting one | Each model provider the API lists, connected through `connect.model` |
| `connections.account.access` | An account's Access section | Whose it is, and a link to share it on NoClick |
| `connections.account.more` | More of an account's page, after its proof | Nothing |

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

Anything else is offered, and the key's scopes decide: what a scope the key lacks would allow, the API refuses, and
Work says so in the API's words where you tried. An agent's sandbox (its files, the `@` files in its box, a shell on it)
is one: it needs the `agents:terminal` scope, which the account's key with every scope (`*`) doesn't hold, so give the
app a key with that scope only if its password should carry it. Approving or declining a call NoClick holds for the
owner's yes is another: it needs the `approvals:answer` scope, which `*` doesn't hold either.

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
- with `agents:terminal`, read an agent's sandbox and open a shell on it;
- with `approvals:answer`, approve or decline a call NoClick holds for your yes, unless the key made it: approving
  one the key couldn't make itself, or one whose terms a person accepts, is refused.

What stays yours, on NoClick's own pages, signed in or from the link NoClick sends you: approving a call held for your
yes (unless the key names `approvals:answer`), raising the account's spending cap, adding funds, linking a phone,
and what the console's list above names. The key's scopes are how you choose the rest: start with none that spend
and without `agents:terminal` or `approvals:answer`, widen them only knowingly, and give the key a spending cap.
Use a long random password, and share it only with people you would hand what the key allows. Signing out drops
this browser's copy of Work's channels and threads.

What differs from NoClick's own Work:

- Who is typing is named as the channel's members name them: the change stream says who by id alone.
- An agent's turns carry the chat's cards, as they draw there (see Chat).
- "Ask NoClick" drafts the message in this app's chat. Home's Find opens the ⌘K palette, which finds Work's channels,
  DMs, agents and spaces while Work is open (each moves within Work's address). No opening a workflow's step: this
  app has no canvas.
- Connecting an app's account or an AI account opens NoClick's connect page in a new tab, and Work waits for the
  account to land. A tool server (MCP) that asks you to sign in is added on NoClick, or with its key.
- Adding funds opens NoClick's page for it. Resources and Connections open this app's.
- An app is drawn with a plain mark and the name read from its type; a coding harness the app has no drawing of
  (OpenCode, Hermes, OpenClaw) with a plain dot.
- Only the account's own agents are listed: NoClick's app also lists those of the account's platform users.

Its slots (`src/screens/work/slots.ts`), besides the shared `connection.mark`, `connect.app` and `connect.model` and the
channels':

| Slot | Where it is | By default |
|---|---|---|
| `work.reply.markdown` | A reply's, a question's or a browser's found text | Drawn as a repository's README is |
| `work.message.file` | A file a texted or emailed message carried, or one an agent made | A link that opens it |
| `work.model.name` | A model's name as people read it | Its id |
| `work.apps` | The apps an agent can use as tools, and whose an account is | The integrations the API lists |
| `work.toolServer.signIn` | Signing in to a tool server added as an agent's tool | Says to add it on NoClick, or give its key |
| `work.funds.add` | Adding funds, where a costly model needs them | A link to NoClick's page for it |
| `work.harness.mark` | The marks of coding harnesses the app has no drawing of | None: a plain dot |
| `work.file.preview` | An agent's workspace file, previewed | A picture, a recording or text at the link the API signed |
| `work.address` | Where Work is, for its pieces drawn elsewhere | This app's `/work` |
| `work.joinedSpace.typing` | Saying you're typing in a space you joined in another account | Through the API, as in your own spaces |

## The frame

The home, `/chat`, `/work`, `/connections`, `/resources`, `/settings` and `/usage` draw inside one frame (`src/screens/shell/AppFrame.tsx`), the one NoClick's
own app draws its pages in. A host tells it where its pages are (`places`): this app's layout route
(`src/routes/shell.tsx`) hands it its routes, NoClick's own app its `?tab=` addresses. On a laptop: a sidebar that
folds to a rail (`⌘\`) and widens from its edge, with your account's name atop it (back to the home), search, the
pages this app serves (Resources opening onto its kinds), and your account at its foot with its menu (Developers,
Usage, Community, the theme, signing out). On a phone: a bar with the page's name and a menu that opens the same sidebar as a
sheet; a page puts its own actions and its way back in that bar. ⌘K (or search) opens the palette: the pages,
Resources' kinds and what Resources and Work handed it, the theme and signing out. The developer console draws the
same frame with its own sidebar (its sections) and its own palette (`src/screens/console/ConsoleShell.tsx`). The
frame reads only the account's status (`GET /v1/status`), and `src/routes/shell.test.tsx` holds it to that.

## Live updates

Every page follows the account's change stream (`watch` in the SDK) where NoClick's API offers it
(`src/sdk/watchLive.ts`): one stream for the whole app, opened when a page follows it and closed half a minute after
none does. Each change names an object and the page reads that object again; a change it can't name, or a stream that
reopened without carrying on from where it was, has the page read everything it shows again. While the stream isn't
live (opening, reconnecting, or refused because the API you call doesn't offer it yet), Work reads what it shows again
when you come back to the tab and every minute while the page is shown, and the stream is asked for again every five
minutes, so it turns on by itself once the API offers it. The console and Resources read again their own way meanwhile;
Usage and Settings read again when you come back to the tab, never on a timer.
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
  `src/screens/resources/resourcesAsKey.test.tsx` does the same for Resources,
  `src/screens/work/workAsKey.test.tsx` for Work, `src/screens/chat/chatAsKey.test.tsx` for Chat,
  `src/screens/connections/connectionsAsKey.test.tsx` for Connections, `src/screens/usage/usageAsKey.test.tsx` for
  Usage, and `src/screens/settings/settingsAsKey.test.tsx` for Settings.

Apache-2.0, as the rest of this repository.
