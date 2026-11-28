/**
 * Your terminal on a shell's socket (a sandbox's, a machine's, beside an agent's work), raw, until its bash ends:
 * what you type goes in as it is (Ctrl-C and Ctrl-D among it), the window's size follows yours, and the exit code is
 * bash's. The Python CLI's `cli._attach_shell` does the same.
 */

import { TerminalConnection } from "../terminal.ts";
import type { TerminalStatus } from "../terminal.ts";
import { CommandError } from "./store.ts";

export async function attachShell(url: string, token: string, renew: () => Promise<string>, command: string): Promise<number> {
  const stdin = process.stdin;
  if (process.platform === "win32" || !stdin.isTTY || !process.stdout.isTTY) {
    throw new CommandError(`${command} needs a terminal on macOS or Linux (on Windows, use WSL).`);
  }
  const size = () => ({ cols: process.stdout.columns || 100, rows: process.stdout.rows || 30 });
  let ended: TerminalStatus | null = null;
  let opened = false;
  const closed = await new Promise<{ code: number; reason: string }>((resolve) => {
    const connection = new TerminalConnection(url, token, {
      ...size(),
      renew,
      onData: (data) => process.stdout.write(data),
      onReady: () => {
        opened = true;
        stdin.setRawMode(true);
        stdin.resume();
        stdin.on("data", (data: Buffer) => connection.write(new Uint8Array(data)));
        process.stdout.on("resize", onResize);
      },
      onState: (status) => {
        if (status.state === "exited") ended = status;
      },
      onClose: ({ code, reason }) => resolve({ code, reason }),
    });
    const onResize = () => connection.resize(size().cols, size().rows);
    stdin.once("end", () => connection.close());
  });
  if (opened) {
    stdin.setRawMode(false);
    stdin.pause();
    stdin.removeAllListeners("data");
    process.stdout.removeAllListeners("resize");
  } else {
    throw new CommandError(`The shell didn't open: ${closed.reason || "closed"}.`);
  }
  const said = ended as TerminalStatus | null;
  if (said?.reason === "idle") process.stderr.write("\nThe shell closed after sitting idle.\n");
  else if (said?.reason !== "exited") process.stderr.write("\nThe connection to the shell was lost.\n");
  const code = said?.raw.exit_code;
  return typeof code === "number" ? code : 0;
}
