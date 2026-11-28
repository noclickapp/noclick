/** What the curated commands take from the process they run in: tests hand in their own. */

import { readFileSync } from "node:fs";
import { hostname } from "node:os";
import { createInterface } from "node:readline";

export interface Host {
  env: Record<string, string | undefined>;
  cwd(): string;
  /** All of stdin, as text. */
  stdin(): Promise<string>;
  stdinIsTty(): boolean;
  sleep(ms: number): Promise<void>;
  /** The fetch every client a command makes uses (the global one unless a test sets it). */
  fetch?: typeof fetch;
  /** Put the profile's key on the default client: what a command that signs in itself (`whoami`) calls. */
  signIn(profile: string): void;
  /** All of stdin, as bytes. */
  stdinBytes(): Buffer;
  /** What's typed, a line at a time, after `prompt()` at a terminal; or each line piped in. Ends at Ctrl-D (or the
   *  pipe's end). */
  lines(prompt: () => string): AsyncIterable<string>;
  /** Bytes to stdout as they are (a file copied to `-`). */
  writeOut(data: Uint8Array): void;
  hostname(): string;
}

async function* typed(prompt: () => string): AsyncGenerator<string> {
  if (!process.stdin.isTTY) {
    const reader = createInterface({ input: process.stdin, crlfDelay: Infinity });
    for await (const line of reader) yield line;
    return;
  }
  const reader = createInterface({ input: process.stdin, output: process.stdout, terminal: true });
  try {
    for (;;) {
      const line = await new Promise<string | null>((done) => {
        const closed = () => done(null);
        reader.once("close", closed);
        reader.question(prompt(), (answer) => {
          reader.off("close", closed);
          done(answer);
        });
      });
      if (line === null) {
        process.stdout.write("\n");
        return;
      }
      yield line;
    }
  } finally {
    reader.close();
  }
}

export const host: Host = {
  env: process.env,
  cwd: () => process.cwd(),
  stdin: async () => readFileSync(0, "utf8"),
  stdinIsTty: () => Boolean(process.stdin.isTTY),
  sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  signIn: () => {
    throw new Error("host.signIn is set by main");
  },
  stdinBytes: () => readFileSync(0),
  lines: typed,
  writeOut: (data) => process.stdout.write(data),
  hostname: () => hostname(),
};
