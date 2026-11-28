/** `noclick shell`: a terminal in a sandbox, on a machine or beside an agent's work, or one command run there. The
 *  Python CLI's `_cli/parts/shell.py` is the same command. */

import { Agent } from "../../agent.ts";
import { Machine } from "../../machine.ts";
import { Project } from "../../project.ts";
import { Sandbox } from "../../sandbox.ts";
import type { Values } from "../args.ts";
import { type Io, printJson, withRun } from "../output.ts";
import { CommandError } from "../store.ts";
import { attachShell } from "../terminal.ts";
import { ID, num, str } from "./kit.ts";

const EXAMPLE = "noclick shell <sandbox> -- ls";
type Where = "sandbox" | "machine" | "agent" | "app";

function quoted(word: string): string {
  return /^[\w@%+=:,./-]+$/.test(word) ? word : `'${word.replace(/'/g, "'\"'\"'")}'`;
}

function target(values: Values): [Where, string, string[]] {
  const words = (values.words as string[] | undefined) ?? [];
  const named = (["machine", "agent", "app"] as const).filter((kind) => str(values, kind));
  if (named.length > 1) throw withRun(new CommandError("Name one place: --machine, --agent or --app.", { nextStep: EXAMPLE }), [EXAMPLE]);
  if (str(values, "conversation") && !str(values, "agent")) {
    throw withRun(new CommandError("--conversation is an agent's.", { nextStep: "Name the agent too." }),
      ["noclick shell --agent <name> --conversation <id>"]);
  }
  if (named.length) return [named[0]!, str(values, named[0]!)!, words];
  if (!words.length) {
    throw withRun(new CommandError("Name where to open it: a sandbox's id, or --machine, --agent or --app.",
      { nextStep: "noclick shell <sandbox>, or noclick shell --machine <name>" }), ["noclick shell <sandbox>", "noclick shell --machine <name>"]);
  }
  return ["sandbox", words[0]!, words.slice(1)];
}

const machine = (ref: string) => (ID.test(ref) ? Machine.fromId(ref) : Machine.fromName(ref));
const agent = (ref: string) => (ID.test(ref) ? Agent.fromId(ref) : Agent.fromName(ref));
const app = (ref: string) => (ID.test(ref) ? Project.fromId(ref) : Project.fromName(ref));

export async function shell(values: Values, io: Io): Promise<number> {
  const [where, ref, command] = target(values);
  if (command.length) return await run(where, ref, command, values, io);
  if (where === "app") {
    throw withRun(new CommandError("An app's live container takes one command at a time, not a terminal.",
      { nextStep: `noclick shell --app ${ref} -- <command>` }), [`noclick shell --app ${ref} -- <command>`]);
  }
  if (!process.stdout.isTTY) {
    const flags = where === "sandbox" ? `${ref} ` : `--${where} ${ref} `;
    throw withRun(new CommandError("noclick shell needs a terminal to open one; pass a command to run it instead.",
      { nextStep: `noclick shell ${flags}-- <command>` }), [`noclick shell ${flags}-- <command>`]);
  }
  const open = async (): Promise<{ url: string; token: string }> => {
    if (where === "sandbox") return await Sandbox.fromId(ref).shell();
    if (where === "machine") return await machine(ref).shell();
    return await agent(ref).sandbox(str(values, "conversation")).shell();
  };
  const opened = await open();
  return await attachShell(opened.url, opened.token, async () => (await open()).token, "noclick shell");
}

async function run(where: Where, ref: string, command: string[], values: Values, io: Io): Promise<number> {
  const line = command.length === 1 ? command[0]! : command.map(quoted).join(" ");
  const timeoutS = num(values, "timeout");
  let result: { stdout: string; stderr: string; exitCode: number | null; timedOut?: boolean; raw?: Record<string, unknown> };
  if (where === "sandbox") result = await Sandbox.fromId(ref).exec(line, { timeoutS }) as typeof result;
  else if (where === "machine") result = await machine(ref).exec(line, { timeoutS }) as typeof result;
  else if (where === "agent") result = await agent(ref).sandbox(str(values, "conversation")).exec(line, { timeoutS });
  else result = await app(ref).live.exec(line, timeoutS ? { timeoutS } : {}) as typeof result;
  if (values.json === true) printJson(io, { stdout: result.stdout, stderr: result.stderr, exit_code: result.exitCode });
  else {
    if (result.stdout) io.out(result.stdout.replace(/\n$/, ""));
    if (result.stderr) process.stderr.write(result.stderr.endsWith("\n") ? result.stderr : `${result.stderr}\n`);
  }
  if (result.timedOut || result.raw?.timed_out) {
    io.err(`It was stopped at its time limit (${timeoutS ?? "the default"}s); --timeout sets another.`);
  }
  return typeof result.exitCode === "number" ? result.exitCode : 1;
}
