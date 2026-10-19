// One file's patch the way a commit page shows it: each hunk under its @@ line, every line numbered on the side
// it exists on, added lines green and removed ones red, and the code in the --code-* colours CodeView uses. A
// hunk is highlighted as one block, so a construct spanning lines keeps its colour; each line is a table row, so
// its numbers never drift from it.
import { useMemo } from 'react';
import { Prism as SyntaxHighlighter, createElement } from 'react-syntax-highlighter';
import { parseUnifiedDiff, type DiffHunk, type DiffLineKind } from '~/lib/unifiedDiff';
import { cn } from '~/lib/utils';
import { CODE_BASE, CODE_THEME, languageFor } from './CodeView';

const ROW: Record<DiffLineKind, string> = {
    add: 'bg-emerald-500/[0.09] dark:bg-emerald-400/[0.09]',
    del: 'bg-red-500/[0.08] dark:bg-red-400/[0.09]',
    ctx: '',
    note: '',
};

const NUMBER: Record<DiffLineKind, string> = {
    add: 'bg-emerald-500/[0.07] text-emerald-700/70 dark:bg-emerald-400/[0.07] dark:text-emerald-300/60',
    del: 'bg-red-500/[0.06] text-red-700/70 dark:bg-red-400/[0.07] dark:text-red-300/60',
    ctx: 'text-muted-foreground/50',
    note: 'text-muted-foreground/50',
};

const MARK: Record<DiffLineKind, string> = { add: '+', del: '−', ctx: '', note: '' };

function Hunk({ hunk, language }: { hunk: DiffHunk; language: string }) {
    // A note ("No newline at end of file") is no code: its row is blank to the highlighter.
    const code = hunk.lines.map((line) => (line.kind === 'note' ? '' : line.text)).join('\n');
    return (
        <>
            <div className="truncate border-y border-border bg-foreground/[0.03] px-4 py-1.5 font-mono text-[12px] text-muted-foreground first:border-t-0 dark:border-foreground/[0.06]">
                <span className="select-none">
                    @@ −{hunk.oldStart} +{hunk.newStart} @@
                </span>
                {hunk.section && <span className="ml-2 text-foreground/60">{hunk.section}</span>}
            </div>
            <SyntaxHighlighter
                language={language}
                style={CODE_THEME}
                PreTag="table"
                CodeTag="tbody"
                customStyle={{ margin: 0, padding: 0, background: 'transparent', display: 'table', width: 'max-content', minWidth: '100%', borderCollapse: 'collapse', overflow: 'visible', fontSize: 12.5, lineHeight: 1.65 }}
                codeTagProps={{ style: { fontFamily: CODE_BASE.fontFamily } }}
                renderer={({ rows, stylesheet, useInlineStyles }) =>
                    hunk.lines.map((line, i) => (
                        <tr key={i} className={ROW[line.kind]} data-line={line.kind}>
                            <td className={cn('w-[3.25em] select-none px-2 text-right align-top tabular-nums', NUMBER[line.kind])}>{line.old ?? ''}</td>
                            <td className={cn('w-[3.25em] select-none px-2 text-right align-top tabular-nums', NUMBER[line.kind])}>{line.new ?? ''}</td>
                            <td
                                aria-hidden
                                className={cn(
                                    'w-5 select-none pl-2 align-top',
                                    line.kind === 'add' ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'
                                )}
                            >
                                {MARK[line.kind]}
                            </td>
                            <td className="pr-6">
                                {line.kind === 'note' ? (
                                    <span className="italic text-muted-foreground">{line.text}</span>
                                ) : rows[i] ? (
                                    createElement({ node: rows[i], stylesheet, useInlineStyles, key: i })
                                ) : (
                                    line.text
                                )}
                            </td>
                        </tr>
                    ))
                }
            >
                {code}
            </SyntaxHighlighter>
        </>
    );
}

export function DiffView({ patch, path }: { patch: string; path: string }) {
    const hunks = useMemo(() => parseUnifiedDiff(patch), [patch]);
    if (!hunks.length) return <p className="px-4 py-6 text-[13.5px] text-muted-foreground">No lines changed: only the file itself (its mode, or an empty file).</p>;
    const language = languageFor(path);
    return (
        <div className="overflow-x-auto scrollbar-subtle" data-testid="diff">
            {hunks.map((hunk, i) => (
                <Hunk key={i} hunk={hunk} language={language} />
            ))}
        </div>
    );
}
