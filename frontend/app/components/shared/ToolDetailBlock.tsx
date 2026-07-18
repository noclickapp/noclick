// Labeled monospace detail block for tool-call payloads (input args, result,
// error) — extracted from the Feed's Agents tab so the agent chat's step
// timeline renders expanded tool calls with the same treatment.

import { cn } from '~/lib/utils';

export function ToolDetailBlock({
    label,
    tone,
    children,
    testId,
}: {
    label: string;
    tone: 'neutral' | 'error';
    children: string;
    testId?: string;
}) {
    return (
        <div data-testid={testId}>
            <div
                className={cn(
                    'text-[0.625rem] uppercase tracking-wide mb-1',
                    tone === 'error'
                        ? 'text-red-600/70 dark:text-red-400/70'
                        : 'text-foreground/30'
                )}
            >
                {label}
            </div>
            <pre
                className={cn(
                    'text-[0.6875rem] rounded-lg p-2.5 overflow-x-auto scrollbar-subtle whitespace-pre-wrap break-words leading-relaxed max-h-48 overflow-y-auto',
                    tone === 'error'
                        ? 'text-red-600/90 dark:text-red-300/90 bg-red-500/[0.06] border border-red-500/10'
                        : 'text-foreground/70 bg-foreground/[0.03] border border-foreground/[0.06]'
                )}
            >
                {children}
            </pre>
        </div>
    );
}
