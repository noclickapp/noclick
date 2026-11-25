// The TypeScript client offers what the Python client offers, under the same names in each language's idiom:
// snake_case is camelCase, an acronym keeps its casing (`handle_openai` is `handleOpenAI`), keyword arguments are
// an options object, and a Python dataclass is an interface (`scripts/surface.ts` pairs the names). Every other
// difference is listed in ACCEPTED with why, and the list only shrinks: an entry that's no longer a difference fails too.

import assert from "node:assert/strict";
import { test } from "node:test";

import { pairMember, pairNames, pythonSurface, typeScriptSurface } from "../scripts/surface.ts";

/** `py:Name`, `py:Name.member`, `ts:Name` or `ts:Name.member`, with the reason it differs. */
const ACCEPTED: Record<string, string> = {
  "py:Client.close": "TS sends with `fetch`, which holds no connection pool to close.",
  "py:Client.aclose": "TS sends with `fetch`, which holds no connection pool to close.",
  "ts:NoClick.asUser": "TS also offers the module's `asUser` on a client; Python's is `noclick.as_user`.",
  "ts:NoClickError.errorType": "Python's class attribute `type`: TS keeps the class's as a static, since each error has its own `type`.",
  "ts:NoClickError.retryAfter": "Python reads every detail as an attribute (`err.retry_after`).",
  "ts:ApprovalRequired.operationId": "Python reads every detail as an attribute (`err.operation_id`).",
  "ts:LookupOptions.options": "Python's `LookupOptions` is the list itself.",
  "ts:Channel.messagesPage": "TS also returns the page with its cursor; Python's `messages()` returns the list.",
  "ts:Channel.repliesPage": "TS also returns the page with its cursor; Python's `replies()` returns the list.",
  "ts:DomainPurchase.purchaseFromId": "A TS static can't narrow `Operation.fromId`'s generic return; Python's `from_id` returns the subclass.",
  "ts:DomainTransfer.transferFromId": "A TS static can't narrow `Operation.fromId`'s generic return; Python's `from_id` returns the subclass.",
  "ts:Job.jobFromId": "A TS static can't narrow `Operation.fromId`'s generic return; Python's `from_id` returns the subclass.",
  "ts:PortRequest.portFromId": "A TS static can't narrow `Operation.fromId`'s generic return; Python's `from_id` returns the subclass.",
  "ts:Dict.size": "Python counts a dict's keys with `len(d)` on the object.",
  "ts:Dict.has": "Python tests a key with `key in d`.",
  "ts:Usage.group": "Python indexes the summary (`usage[group_id]`); TS has no `[]` overloading.",
  "ts:QueryResult.length": "Python takes `len(result)`.",
  "ts:Repo.readText": "Python's `read()` returns `bytes` and `.decode()` makes the text.",
  "ts:SandboxFiles.readText": "Python's `read()` returns `bytes` and `.decode()` makes the text.",
  "ts:Terminal.connect": "A terminal is opened by a person's browser: Python's server hands it `url` and `token`.",
  "ts:TerminalConnection": "A terminal is opened by a person's browser: Python's server hands it `url` and `token`.",
  "ts:TERMINAL_CLOSED_FOR_GOOD": "A terminal is opened by a person's browser: Python's server hands it `url` and `token`.",
  "ts:TERMINAL_RENEW": "A terminal is opened by a person's browser: Python's server hands it `url` and `token`.",
  "ts:SandboxShell.connect": "A shell is opened by a person's browser: Python's server hands it `url` and `token`.",
  "ts:Browser.view": "A live view is shown in a person's browser: Python's server hands it `url` and `token`.",
  "ts:BrowserLiveView.connect": "A live view is shown in a person's browser: Python's server hands it `url` and `token`.",
  "ts:BrowserViewConnection": "A live view is shown in a person's browser: Python's server hands it `url` and `token`.",
  "ts:BROWSER_VIEW_CLOSE": "A live view is shown in a person's browser: Python's server hands it `url` and `token`.",
  "ts:BrowserLink.view": "A link's browser is shown in the person's own browser, over the link's socket.",
  "ts:Room.access": "A page's place in a room is held by a browser: Python's server publishes, asks, reads and mints a token.",
  "ts:Room.answer": "A page's place in a room is held by a browser: Python's server publishes, asks, reads and mints a token.",
  "ts:Room.broadcast": "A page's place in a room is held by a browser: Python's server publishes, asks, reads and mints a token.",
  "ts:Room.join": "A page's place in a room is held by a browser: Python's server publishes, asks, reads and mints a token.",
  "ts:Room.leave": "A page's place in a room is held by a browser: Python's server publishes, asks, reads and mints a token.",
  "ts:Room.me": "A page's place in a room is held by a browser: Python's server publishes, asks, reads and mints a token.",
  "ts:Room.on": "A page's place in a room is held by a browser: Python's server publishes, asks, reads and mints a token.",
  "ts:Room.presence": "A page's place in a room is held by a browser: Python's server publishes, asks, reads and mints a token.",
  "ts:Room.runs": "A page's place in a room is held by a browser: Python's server publishes, asks, reads and mints a token.",
  "ts:Room.scope": "A page's place in a room is held by a browser: Python's server publishes, asks, reads and mints a token.",
  "ts:Room.status": "A page's place in a room is held by a browser: Python's server publishes, asks, reads and mints a token.",
  "ts:Room.stop": "A page's place in a room is held by a browser: Python's server publishes, asks, reads and mints a token.",
  "ts:RoomRefused": "A page's place in a room is held by a browser: Python's server publishes, asks, reads and mints a token.",
  "ts:AgentLink.join": "A page's place in a room is held by a browser: Python's server mints the visitor's token (`room_token`).",
  "py:Skill.from_dir": "Reading a folder needs a file system, which TS in a browser lacks: TS passes the files to `Skill.create`.",
};

// Idiom on both sides: how a value prints and serializes.
const IDIOM = new Set(["toString", "toJSON"]);

function differences(): string[] {
  const py = pythonSurface();
  const { entries: tsSurface } = typeScriptSurface();
  const paired = pairNames(py.keys(), tsSurface.keys());
  const tsPaired = new Set(paired.values());
  const found = new Set<string>();
  for (const [name, item] of py) {
    const tsName = paired.get(name);
    if (!tsName) {
      found.add(`py:${name}`);
      continue;
    }
    const tsItem = tsSurface.get(tsName)!;
    const tsMembers = [...tsItem.members.keys()];
    const met = new Set<string>();
    for (const member of item.members) {
      const twin = pairMember(name, member, [...tsMembers, ...tsItem.runtime]);
      if (twin) met.add(twin);
      else found.add(`py:${name}.${member}`);
    }
    for (const member of tsMembers) if (!met.has(member) && !IDIOM.has(member)) found.add(`ts:${tsName}.${member}`);
  }
  for (const [name, item] of tsSurface) {
    // An options object or a union is how TS spells keyword arguments and `Literal[...]`: not a difference.
    if (!tsPaired.has(name) && item.kind !== "type" && item.kind !== "interface") found.add(`ts:${name}`);
  }
  // A difference a class inherits is its base's: report it there once.
  const inherited = (key: string) => {
    const [side, rest] = key.split(":");
    const [name, member] = rest.split(".");
    if (!member) return false;
    const bases = (side === "py" ? py.get(name)?.bases : tsSurface.get(name)?.bases) ?? [];
    return bases.some((base) => found.has(`${side}:${base}.${member}`));
  };
  return [...found].filter((key) => !inherited(key)).sort();
}

test("the TypeScript client offers what the Python client offers", () => {
  const found = differences();
  const unexpected = found.filter((key) => !(key in ACCEPTED));
  assert.deepEqual(unexpected, [], `differences between the clients (add the missing name, or accept it with why):\n${unexpected.join("\n")}`);
  const stale = Object.keys(ACCEPTED).filter((key) => !found.includes(key));
  assert.deepEqual(stale, [], `accepted differences that no longer differ (remove them):\n${stale.join("\n")}`);
});
