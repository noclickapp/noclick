// The builder panel's header: the automation it changes, in the pages' serif with the automation's own mark, so what
// a message changes is never a line under the composer; the connection only when it drops; history, a new chat and
// close. On a phone the app's bar already names the automation and takes the buttons, as every page's actions go
// there, and with history open its way back leads to the chat; the panel keeps only a dropped connection.
import type { ReactNode } from 'react';
import { ChevronLeft, History, SquarePen, X } from 'lucide-react';
import { LiveDot } from '~/components/coordinator/inline/primitives';
import { ShortcutTooltip } from '~/components/shared/ShortcutTooltip';
import { PhoneBarActions, PhoneBarBack } from '~/components/shell/AppShell';
import { AutomationMark } from '~/components/shell/glyphs';
import { DISPLAY } from '~/components/shell/titles';
import { cn } from '~/lib/utils';

export type BuilderConnection = 'connected' | 'reconnecting' | 'offline';

const ICON_BUTTON =
    'inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring aria-pressed:bg-foreground/[0.07] aria-pressed:text-foreground';
const GLYPH = 'h-[17px] w-[17px]';

function IconButton({ label, keys, onClick, pressed, children, testId }: { label: string; keys?: string[]; onClick?: () => void; pressed?: boolean; children: ReactNode; testId?: string }) {
    return (
        <ShortcutTooltip label={label} keys={keys}>
            <button type="button" aria-label={label} aria-pressed={pressed} className={ICON_BUTTON} onClick={onClick} data-testid={testId}>
                {children}
            </button>
        </ShortcutTooltip>
    );
}

/** The connection, said only when it isn't there. */
function ConnectionNote({ connection }: { connection: BuilderConnection }) {
    if (connection === 'connected') return null;
    return (
        <span
            className={cn('inline-flex shrink-0 items-center gap-1.5 text-[12.5px]', connection === 'offline' ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground')}
            data-testid="builder-connection"
        >
            {connection === 'reconnecting' ? <LiveDot className="h-1.5 w-1.5" /> : <span className="h-1.5 w-1.5 rounded-full bg-current" />}
            {connection === 'reconnecting' ? 'Reconnecting' : 'Offline'}
        </span>
    );
}

export function BuilderHeader({
    workflowName,
    connection,
    historyOpen,
    onToggleHistory,
    onNewChat,
    onClose,
    isMobile,
}: {
    workflowName?: string;
    connection: BuilderConnection;
    historyOpen: boolean;
    onToggleHistory: () => void;
    onNewChat: () => void;
    /** A laptop's close (Esc); a phone closes from its bar's Builder toggle. */
    onClose?: () => void;
    isMobile: boolean;
}) {
    const actions = (
        <div className="flex shrink-0 items-center gap-0.5">
            <IconButton label="History" pressed={historyOpen} onClick={onToggleHistory} testId="builder-history">
                <History className={GLYPH} strokeWidth={1.75} />
            </IconButton>
            <IconButton label="New chat" onClick={onNewChat} testId="builder-new-chat">
                <SquarePen className={GLYPH} strokeWidth={1.75} />
            </IconButton>
            {!isMobile && onClose && (
                <IconButton label="Close" keys={['esc']} onClick={onClose}>
                    <X className={GLYPH} strokeWidth={1.75} />
                </IconButton>
            )}
        </div>
    );
    const name = workflowName || 'Builder';
    if (isMobile) {
        return (
            <>
                {connection !== 'connected' && (
                    <div className="px-4 pt-2">
                        <ConnectionNote connection={connection} />
                    </div>
                )}
                {historyOpen && <PhoneBarBack label="Back to the chat" title="Earlier chats" onBack={onToggleHistory} />}
                <PhoneBarActions>{actions}</PhoneBarActions>
            </>
        );
    }
    return (
        <header className="flex h-[60px] shrink-0 items-center gap-2.5 pl-4 pr-2" data-testid="builder-header">
            {historyOpen ? (
                <IconButton label="Back to this chat" onClick={onToggleHistory}>
                    <ChevronLeft className="h-[18px] w-[18px]" strokeWidth={1.75} />
                </IconButton>
            ) : (
                <AutomationMark className="h-5 w-5 shrink-0" />
            )}
            <h2 className={cn(DISPLAY, 'min-w-0 flex-1 truncate text-[25px] leading-[1.15] text-foreground')} title={historyOpen ? undefined : name}>
                {historyOpen ? 'Earlier chats' : name}
            </h2>
            <ConnectionNote connection={connection} />
            {actions}
        </header>
    );
}
