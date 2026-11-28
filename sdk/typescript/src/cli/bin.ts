#!/usr/bin/env node
// `npx noclick`: runs the command line and exits with its status (src/cli/main.ts).
import { INTERRUPTED } from "./exits.ts";
import { takeInterrupt } from "./host.ts";
import { main } from "./main.ts";

// The reader (`| head`) stopped reading: nothing more to say, to anyone.
process.stdout.on("error", (err: NodeJS.ErrnoException) => {
  if (err.code === "EPIPE") process.exit(0);
  throw err;
});
process.on("SIGINT", () => {
  process.stderr.write("\n");
  if (takeInterrupt()) return;
  process.exit(INTERRUPTED);
});

process.exitCode = await main(process.argv.slice(2));
