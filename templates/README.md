# NoClick's templates

Each folder here is a space template: a package someone adds to their NoClick account, from one agent up to a team
with its own channels, skills and app. These are the ones NoClick lists first in its template gallery, in the app and
at [noclick.com/templates](https://noclick.com/templates).

A template is a repository. At its root, `space.json` names what it makes and what it asks for:

| Key | What it is |
| --- | --- |
| `channels` | Its channels, the agents in each, and anything posted on a schedule |
| `agents` | Its agents: each one's job, harness, tools, skills and memories, and its instructions in a Markdown file |
| `skills`, `memories` | Folders of Agent Skills, and files of starting notes |
| `automations`, `stores`, `app` | Workflows, empty databases and buckets, and an app's code with its `noclick.json` |
| `asks` | The accounts it needs connected, secrets by name, and a monthly budget for its agents |
| `gallery` | How the gallery shows it: its job, its own screenshots, and an example conversation per channel |

Where an account would name one of its connections, a template names the integration instead (`gmail`, `canva`), and
`asks.connections` lists each, so nothing in it belongs to anyone. It never holds messages, data, people, accounts or
secrets' values.

## Adding one

Find it in the gallery and tap **Use this template**, or send its address to `POST /v1/workspaces/from_template`. You
see one page of what it makes, what it asks for and what it costs before anything is made; then all of it is made, or
none of it.

## Writing one

The quickest way is to set up a space you like and use **Save as template** in its menu: NoClick writes the
repository for you. To list a template in the gallery, make its repository public; NoClick reviews it before it's
listed. To change one of these, open a pull request against this folder: each change is reviewed like code, then
published again.

The full format is in the docs: [Save a space as a template](https://noclick.com/docs/guide/workspaces#save-it-as-a-template).
