/**
 * `--max-usd`: anything that spends says what it would cost before it runs, and runs only under the ceiling the
 * command line set. The figure is NoClick's own estimate (the SDK's `estimate`). As `noclick/_cli/spend.py`.
 */

import { type Estimate, type EstimateRequestItem, estimate } from "../estimate.ts";
import { OverLimit } from "./exits.ts";
import type { Io } from "./output.ts";

export function usd(value: number | null | undefined): string {
  if (value === null || value === undefined) return "-";
  return `$${value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/** Price `items`, say it on stderr, and refuse (`OverLimit`, exit 4) when it passes `maxUsd`. `what` names the
 *  action ("This session"), `per` what the figure covers ("a month", "at most"). */
export async function check(
  io: Io, items: EstimateRequestItem[], maxUsd: number | null | undefined, options: { what: string; per?: string },
): Promise<Estimate> {
  const priced = await estimate(items);
  const total = priced.monthlyUsd;
  const said = `${options.what} costs about ${usd(total)} ${options.per ?? "a month"}`;
  const capped = maxUsd !== null && maxUsd !== undefined;
  if (capped && total > maxUsd) {
    throw new OverLimit(`${said}, over --max-usd ${usd(maxUsd)}: nothing was done.`, {
      nextStep: "Raise --max-usd, or see each line with: noclick estimate --json",
      details: { estimate_usd: total, max_usd: maxUsd },
    });
  }
  io.err(`${said}${capped ? ` (under --max-usd ${usd(maxUsd)})` : ""}.`);
  return priced;
}
