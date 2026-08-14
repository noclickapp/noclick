// The "Set up in minutes" numbered walk used by the marketing pages: an
// icon-or-number circle per step joined by a connector line, with a short
// title, body and optional inline extras (command blocks, toggles). Extracted
// as a shared component so every surface that explains setup stays visually
// identical instead of each page rolling its own list.

import type { ReactNode } from 'react';

export interface SetupStepItem {
    key: string;
    /** Brand/lucide mark for the circle; falls back to the step number. */
    icon?: ReactNode;
    title: string;
    body?: string;
    /** Extra content under the body (command blocks, toggles, …). */
    children?: ReactNode;
}

export function SetupSteps({ steps }: { steps: SetupStepItem[] }) {
    return (
        <ol className="m-0 max-w-2xl list-none p-0">
            {steps.map((step, i) => (
                <li
                    key={step.key}
                    className="relative flex gap-4 pb-8 last:pb-0"
                >
                    {/* Connector: starts flush with the circle's bottom edge
                        (top-8), centered on its axis, ending exactly at the
                        next circle's top (this li's own bottom edge). */}
                    {i < steps.length - 1 && (
                        <span
                            aria-hidden="true"
                            className="absolute bottom-0 left-4 top-8 w-px -translate-x-1/2 bg-foreground/[0.1]"
                        />
                    )}
                    <span className="relative z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-foreground/[0.08]">
                        {step.icon ?? (
                            <span className="text-[12.5px] font-semibold tabular-nums text-foreground/55">
                                {i + 1}
                            </span>
                        )}
                    </span>
                    <div className="min-w-0 pt-[5px]">
                        <p className="m-0 text-sm font-medium leading-snug text-foreground/85">
                            {step.title}
                        </p>
                        {step.body && (
                            <p className="m-0 mt-1.5 text-[13.5px] leading-relaxed text-muted-foreground">
                                {step.body}
                            </p>
                        )}
                        {step.children}
                    </div>
                </li>
            ))}
        </ol>
    );
}
