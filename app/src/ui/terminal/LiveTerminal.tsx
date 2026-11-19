// A terminal a person types into (Work's shell on an agent's sandbox): the same xterm.js, in the same well and colours
// as Watch, but live: it shows what the sandbox prints and sends what's typed (and its size) back, through its websocket
// (`connect`). xterm.js answers a program's own questions (where the cursor is, what terminal this is), as a desktop
// terminal does.
import { useEffect, useImperativeHandle, useRef, type Ref } from 'react';
import type { Terminal as XTerm } from '@xterm/xterm';
import '@xterm/xterm/css/xterm.css';
import type { Terminal as TakenTerminal, TerminalConnection, TerminalStatus } from 'noclick';
import { cn } from '@/ui/utils';
import { FONT, themeOf, WELL, type TerminalApi } from './theme';

export function LiveTerminal({
    terminal,
    onState,
    onClosed,
    fontSize = 12.5,
    radius = 14,
    className,
    apiRef,
}: {
    /** The shell, with the token that opens it once. */
    terminal: Pick<TakenTerminal, 'connect'>;
    onState: (status: TerminalStatus) => void;
    /** Its connection closed: `final` once it's ended (or it can't open again with this token), with the server's
     *  `reason` when it gave one (a refusal says why). */
    onClosed: (final: boolean, reason?: string) => void;
    fontSize?: number;
    radius?: number;
    className?: string;
    apiRef?: Ref<TerminalApi | null>;
}) {
    const well = useRef<HTMLDivElement>(null);
    const host = useRef<HTMLDivElement>(null);
    const term = useRef<XTerm | null>(null);
    const said = useRef({ onState, onClosed });
    said.current = { onState, onClosed };

    useImperativeHandle(apiRef, () => ({
        copy: async () => {
            const t = term.current;
            const selection = !!t?.hasSelection();
            let text = selection ? t!.getSelection() : '';
            if (t && !selection) {
                t.selectAll();
                text = t.getSelection();
                t.clearSelection();
            }
            try {
                await navigator.clipboard.writeText(text);
            } catch {
                // The clipboard refused (an unfocused page).
            }
            return selection ? 'selection' : 'all';
        },
    }));

    useEffect(() => {
        let gone = false;
        let connection: TerminalConnection | null = null;
        let sized: ResizeObserver | null = null;
        let themed: MutationObserver | null = null;
        void (async () => {
            const [{ Terminal }, { FitAddon }] = await Promise.all([import('@xterm/xterm'), import('@xterm/addon-fit')]);
            await document.fonts.ready;
            if (gone || !host.current || !well.current) return;
            const live = () => ({ ...themeOf(well.current!), cursor: themeOf(well.current!).foreground });
            const t = new Terminal({ cursorBlink: true, fontFamily: FONT, fontSize, lineHeight: 1.2, scrollback: 5_000, theme: live() });
            const fitter = new FitAddon();
            t.loadAddon(fitter);
            t.open(host.current);
            term.current = t;
            fitter.fit();
            try {
                connection = terminal.connect({
                    cols: t.cols,
                    rows: t.rows,
                    onData: (bytes) => t.write(bytes),
                    onReady: (status) => {
                        said.current.onState(status);
                        t.focus();
                    },
                    onState: (status) => said.current.onState(status),
                    onClose: ({ final, reason }) => !gone && said.current.onClosed(final, reason || undefined),
                });
            } catch {
                // Its token opened it once already (a remount): open it again with a fresh one.
                said.current.onClosed(false);
                return;
            }
            const open = connection;
            t.onData((data) => open.write(data));
            t.onResize(({ cols, rows }) => open.resize(cols, rows));
            host.current.setAttribute('data-terminal-ready', '1');
            sized = new ResizeObserver(() => {
                if (host.current && host.current.clientWidth > 80 && host.current.clientHeight > 40) fitter.fit();
            });
            sized.observe(host.current);
            themed = new MutationObserver(() => well.current && (t.options.theme = live()));
            themed.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
        })();
        return () => {
            gone = true;
            connection?.close();
            sized?.disconnect();
            themed?.disconnect();
            term.current?.dispose();
            term.current = null;
        };
        // One connection per shell (its token opens it once).
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [terminal, fontSize]);

    return (
        <div ref={well} className={cn(WELL, 'relative min-h-0 overflow-hidden', className)} style={{ borderRadius: radius }} data-testid="live-terminal">
            <div className="absolute inset-0 px-3 py-2.5">
                <div ref={host} className="h-full w-full" />
            </div>
        </div>
    );
}
