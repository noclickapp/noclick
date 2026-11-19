// Your own shell in a drawer, as t3code's terminal drawer runs yours in a thread's worktree: `bash -l` over the terminal
// websocket, in Watch's xterm.js well (LiveTerminal). Work's agent page opens one on the agent's sandbox, beside its
// work; a machine's page opens one on the machine itself. Whoever opens it says where the token comes from.
import { useEffect, useRef, useState } from 'react';
import { SquareTerminal, X } from 'lucide-react';
import type { Terminal as TakenTerminal } from 'noclick';
import { HAIRLINE } from '@/ui/primitives';
import { BUTTON_SECONDARY } from '@/ui/buttons';
import { cn } from '@/ui/utils';
import { LiveTerminal } from '@/ui/terminal/LiveTerminal';
import { ICON_BUTTON } from '../ui';

const SMALL_SECONDARY = BUTTON_SECONDARY.replace('h-9', 'h-8').replace(
    'px-4',
    'px-3'
);
/** Most of the window on a machine's page. Under a file on an agent's page, a column of set height, the percentage
 *  cap holds it to about half; a machine's page is as tall as its content, so there the cap resolves to nothing. */
const ROOM = 'h-[min(70dvh,760px)] max-h-[55%] min-h-[300px] max-sm:h-[80dvh]';

/** A shell's single-use token and its connection, as `POST …/shell` answers it. */
export type OpenedShell = Pick<TakenTerminal, 'connect'> & { token: string };

export function ShellDrawer({
    label,
    running,
    open: openShell,
    asleep,
    onClose,
    className,
}: {
    /** What its bar says: whose shell, and where. */
    label: string;
    running: boolean;
    /** Asks for a token and the connection it opens, once per shell. */
    open: () => Promise<OpenedShell>;
    /** Said while it can't run (its sandbox or machine isn't up). */
    asleep: string;
    onClose: () => void;
    className?: string;
}) {
    const [shell, setShell] = useState<OpenedShell | null>(null);
    const [ended, setEnded] = useState<string | null>(null);
    const opening = useRef(false);
    const open = async () => {
        if (opening.current) return;
        opening.current = true;
        setEnded(null);
        try {
            setShell(await openShell());
        } catch (error) {
            setEnded(error instanceof Error ? error.message : String(error));
        } finally {
            opening.current = false;
        }
    };
    useEffect(() => {
        if (running) void open();
        // One shell per opening of the drawer.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [running]);
    return (
        <div
            className={cn(
                'flex shrink-0 flex-col border-t',
                ROOM,
                HAIRLINE,
                className
            )}
            data-testid="shell-drawer"
        >
            {/* The ✕ has the same 8px above, below and to its right, so it clears the corner's curve; its glyph lines
                up with the mark's 16px on the left. */}
            <div
                className={cn(
                    'flex shrink-0 items-center gap-2.5 border-b py-2 pl-4 pr-2 text-[13px] text-muted-foreground',
                    HAIRLINE
                )}
            >
                <SquareTerminal
                    className="h-4 w-4 shrink-0"
                    strokeWidth={1.75}
                />
                <span className="min-w-0 flex-1 truncate">{label}</span>
                <button
                    type="button"
                    aria-label="Close the shell"
                    onClick={onClose}
                    className={ICON_BUTTON}
                >
                    <X className="h-4 w-4" />
                </button>
            </div>
            {shell ? (
                <LiveTerminal
                    key={shell.token}
                    terminal={shell}
                    fontSize={12.5}
                    radius={0}
                    // Edge to edge in the drawer, whose own borders frame it.
                    className="flex-1 ring-0"
                    onState={() => undefined}
                    onClosed={(final, reason) => {
                        setShell(null);
                        setEnded(
                            reason ??
                                (final
                                    ? 'The shell ended.'
                                    : 'The connection dropped.')
                        );
                    }}
                />
            ) : (
                <div className="flex flex-1 flex-col items-center justify-center gap-3 px-6 text-center text-[13px] text-muted-foreground">
                    <span className="max-w-[52ch] text-balance">
                        {ended ?? (running ? 'Opening a shell…' : asleep)}
                    </span>
                    {ended && running && (
                        <button
                            type="button"
                            onClick={() => void open()}
                            className={SMALL_SECONDARY}
                        >
                            Open another
                        </button>
                    )}
                </div>
            )}
        </div>
    );
}
