// Small pieces the Apps drawer shares: an app's URL as a link, a branch name, a tag, a choice with a sentence about the
// picked option, and log lines as a terminal shows them.
import type { ReactNode } from 'react';
import { ExternalLink, GitBranch } from 'lucide-react';
import { HAIRLINE } from '@/ui/primitives';
import { cn } from '@/ui/utils';
import type { LogLine } from 'noclick';
import { formatLogTime } from '@/screens/console/lib/format';
import { Segmented } from '../../ui/Segmented';
import type { ChoiceOption } from './AppsFormat';

/** `https://booking.noclick.site` → `booking.noclick.site`. */
export const hostOf = (url: string) => url.replace(/^https?:\/\//, '').replace(/\/$/, '');

/** An app's URL as a link that doesn't open the row it sits in. */
export function AppUrl({ url, className }: { url: string; className?: string }) {
    return (
        <a href={url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()} className={className ?? 'inline-flex min-w-0 items-center gap-1 text-foreground/80 hover:text-foreground hover:underline'}>
            <span className="truncate">{hostOf(url)}</span>
            <ExternalLink aria-hidden className="h-3 w-3 shrink-0 text-muted-foreground" />
        </a>
    );
}

export function BranchName({ name, className }: { name: string; className?: string }) {
    return (
        <span className={cn('inline-flex min-w-0 items-center gap-1 font-mono text-[12px] text-foreground', className)}>
            <GitBranch aria-hidden className="h-3 w-3 shrink-0 text-muted-foreground" />
            <span className="truncate">{name}</span>
        </span>
    );
}

export function Tag({ children }: { children: ReactNode }) {
    return <span className={cn('inline-flex h-5 shrink-0 items-center rounded-full border px-2 text-[12px] font-medium text-foreground/80', HAIRLINE)}>{children}</span>;
}

/** An exclusive choice with the picked option's sentence under it. */
export function Choice<T extends string>({ label, options, value, onChange }: { label: string; options: readonly ChoiceOption<T>[]; value: T; onChange: (value: T) => void }) {
    return (
        <div className="flex flex-col gap-1.5">
            <span className="text-[12px] font-medium text-muted-foreground">{label}</span>
            <Segmented label={label} options={options} value={value} onChange={onChange} className="self-start" />
            <p className="m-0 text-[12px] text-muted-foreground">{options.find((o) => o.value === value)?.sentence}</p>
        </div>
    );
}

const LEVEL_CLASS: Record<string, string> = {
    info: 'text-muted-foreground',
    warn: 'font-medium text-foreground',
    error: 'font-medium text-red-600 dark:text-red-400',
};

/** Log lines as the terminal shows them: time, level, message; errors in red. */
export function AppsLogLines({ lines, label, empty, className }: { lines: readonly LogLine[]; label: string; empty: string; className?: string }) {
    if (!lines.length) return <p className="m-0 text-[13px] text-muted-foreground">{empty}</p>;
    return (
        <ol aria-label={label} className={cn('m-0 max-h-[28rem] list-none overflow-auto rounded-lg border bg-foreground/[0.03] px-0 py-2 font-mono text-[12px] leading-5', HAIRLINE, className)}>
            {lines.map((line, i) => (
                <li key={i} className="flex gap-3 px-3">
                    <time className="shrink-0 tabular-nums text-muted-foreground" dateTime={line.at?.toISOString()}>
                        {line.at ? formatLogTime(line.at) : ''}
                    </time>
                    <span className={cn('w-10 shrink-0', LEVEL_CLASS[line.level])}>{line.level}</span>
                    <span className={cn('min-w-0 whitespace-pre-wrap break-words', line.level === 'error' ? LEVEL_CLASS.error : 'text-foreground')}>{line.message}</span>
                </li>
            ))}
        </ol>
    );
}
