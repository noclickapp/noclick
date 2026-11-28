/**
 * An error's words as the command line says them, as the Python CLI's `cli._for_the_terminal` does, from the
 * error's fields and the manifest's `screens.said`: what isn't there by its kind (the SDK's `details.kind`) with the
 * command that makes it, an API that couldn't be reached by its host and why, and a step written for code said as the
 * command that takes it.
 */

import { API_KEY_ENV } from "../client.ts";
import { APIConnectionError, NotFound, Unauthenticated } from "../errors.ts";
import { commandLine, type Said } from "./output.ts";
import type { Spec } from "./spec.ts";

const BUILD_LOG_STEP = /Read its build log: GET \/v1\/deployments\/([\w-]+)\/logs\?kind=build\.?/g;
const SETTING_SET = /app\.settings\.set\(("[^"]*"), ("[^"]*")\)/g;

/** An API that couldn't be reached, said plainly: its host (its whole URL when NOCLICK_API_URL names another), why,
 *  and what to do. */
export function unreachable(spec: Spec, apiUrl: string, cause: string): { message: string; nextStep: string } {
  const words = spec.manifest.screens.said;
  const why = words.unreachable.find(([found]) => cause.toLowerCase().includes(found.toLowerCase()))?.[1] ?? (cause || "no answer");
  const standard = apiUrl.replace(/\/+$/, "") === words.default_api;
  return {
    message: `Can't reach ${standard ? words.default_api.split("//")[1] : apiUrl} (${why}).`,
    nextStep: standard ? "Check your network, then try again." : `Check your network, and NOCLICK_API_URL (${apiUrl}), then try again.`,
  };
}

/** What a step written for code says, as the command that takes it (added to `run`). */
export function cliWords(text: string, run: string[]): string {
  return text.replace(BUILD_LOG_STEP, (_, id: string) => {
    run.push(`noclick logs --build --deployment ${id}`);
    return `Read its build log: noclick logs --build --deployment ${id}`;
  }).replace(SETTING_SET, (_, name: string, value: string) => {
    run.push(`noclick env set ${name.slice(1, -1)}=${value.slice(1, -1)}`);
    return run[run.length - 1]!;
  });
}

export function forTheTerminal(err: { message?: string; nextStep?: string | null; details?: Record<string, unknown> }, spec: Spec): Said {
  const words = spec.manifest.screens.said;
  const details = err.details ?? {};
  const run: string[] = [];
  if (err instanceof Unauthenticated && !(err as { run?: string[] }).run?.length) { // the API refused the key itself
    return {
      message: "This key isn't valid: run noclick login.",
      nextStep: `${err.message ?? ""} Sign in again, or set ${API_KEY_ENV} to a key that works.`.trimStart(), run: ["noclick login"],
    };
  }
  if (err instanceof APIConnectionError && typeof details.api_url === "string") {
    return { ...unreachable(spec, details.api_url, String(details.cause ?? "")), run };
  }
  const kind = typeof details.kind === "string" ? details.kind : null;
  const name = typeof details.name === "string" ? details.name : "";
  if (err instanceof NotFound && kind) {
    const word = words.kind_words[kind] ?? kind.replace(/_/g, " ");
    const message = name ? `No ${word} is named '${name}'.` : String(err.message);
    const makes = words.makes[kind];
    if (makes) {
      run.push(makes[1].replace("{name}", name || `<${word}>`));
      return { message, nextStep: `${makes[0]}: ${run[0]}`, run };
    }
    const route = words.made_by[kind];
    if (!route) return { message, nextStep: null, run };
    const op = spec.forCall("POST", route);
    let made = op ? commandLine(op, op.path) : `noclick api POST ${route}`;
    if (op && name && op.params.some((p) => p.name === "name" && p.in === "body")) made += ` --name ${name}`;
    run.push(made);
    return { message, nextStep: `Make it first: ${made}`, run };
  }
  let step = err.nextStep ?? null;
  if (step?.startsWith("Run statements that write with execute")) step = "Run it again with --write.";
  else if (step) step = cliWords(step, run);
  return { message: cliWords(String(err.message ?? ""), run), nextStep: step, run };
}
