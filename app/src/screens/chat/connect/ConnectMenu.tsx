// The chat's Connect button: the other ways into this same conversation. WhatsApp and iMessage (how NoClick is texted,
// its host's: `chat.connect.text`), email (NoClick's own address, `chat.connect.email`), and MCP, which opens the setup
// guides for using NoClick from an AI client.
import { useContext, useRef, useState, type KeyboardEvent } from 'react';
import { ChevronDown, ChevronRight, Loader2 } from 'lucide-react';
import { IoMail } from 'react-icons/io5';
import { useSlot } from '@/slots';
import { ConsoleContext } from '@/screens/console/hooks/useConsole';
import { MCP_URL } from '@/screens/console/lib/mcpUrl';
import { AppTile, ChannelTile, type TextApp } from '@/ui/AppTile';
import { MENU_PANEL, MenuBackRow, MenuItem, moveBetweenMenuItems } from '@/ui/chat/ComposerAddMenu';
import { McpMark } from '@/ui/codingAgentMarks';
import { MCPSetupModal } from '@/ui/MCPSetupModal';
import { Popover, PopoverContent, PopoverTrigger } from '@/ui/popover';
import { useIsMobile } from '@/ui/useIsMobile';
import { cn } from '@/ui/utils';
import { useChatContext } from '../context';
import { CONNECT_EMAIL, CONNECT_TEXT } from '../slots';
import { TEXT_APPS } from './textApp';

/** What the setup guides say NoClick's MCP server does, where its host names no other. */
export const MCP_INTRO = 'Build automations, agents, apps and more on NoClick from Claude, ChatGPT, Cursor and other MCP clients.';

type View = 'menu' | TextApp | 'email';
type Way = TextApp | 'email' | 'mcp';

// Email in Mail's blue and MCP on graphite, beside the texting apps' own tiles.
const McpGlyph = ({ className }: { className?: string }) => <McpMark className={className} />;
const TILES = {
    email: { background: 'linear-gradient(180deg, #62c6ff 0%, #1b7cf3 100%)', glyph: IoMail },
    mcp: { background: 'linear-gradient(180deg, #55555b 0%, #1d1d20 100%)', glyph: McpGlyph },
};

function WayTile({ way, className }: { way: Way; className?: string }) {
    if (way === 'email' || way === 'mcp') return <AppTile glyph={TILES[way].glyph} background={TILES[way].background} size="sm" className={className} />;
    return <ChannelTile channel={way} size="sm" className={className} />;
}

// The button is its tiles, overlapping like a hand of cards that spreads under the pointer, and its name: no pill
// around it. The page's own background keeps a thread scrolling under it from showing through.
const TRIGGER =
    'group inline-flex h-9 shrink-0 items-center gap-2 rounded-full bg-background pl-1 pr-2.5 text-[14px] font-medium text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';
const WAYS: Way[] = ['whatsapp', 'imessage', 'email', 'mcp'];
const FAN = [
    '-rotate-[8deg] group-hover:-translate-x-[3px] group-hover:-rotate-[12deg] group-data-[state=open]:-translate-x-[3px] group-data-[state=open]:-rotate-[12deg]',
    '-rotate-[3deg] group-hover:-translate-x-px group-hover:-rotate-[4deg] group-data-[state=open]:-translate-x-px group-data-[state=open]:-rotate-[4deg]',
    'rotate-[3deg] group-hover:translate-x-px group-hover:rotate-[4deg] group-data-[state=open]:translate-x-px group-data-[state=open]:rotate-[4deg]',
    'rotate-[8deg] group-hover:translate-x-[3px] group-hover:rotate-[12deg] group-data-[state=open]:translate-x-[3px] group-data-[state=open]:rotate-[12deg]',
];
const GLOSS: Record<TextApp, string> = { whatsapp: 'Text it from your phone', imessage: 'Text it from your iPhone' };

/** `onAsk` drafts a message to NoClick, for what it sets up itself (its own email address). */
export function ConnectMenu({ align = 'start', onAsk }: { align?: 'start' | 'end'; onAsk: (text: string) => void }) {
    const [open, setOpen] = useState(false);
    const [view, setView] = useState<View>('menu');
    const [mcpOpen, setMcpOpen] = useState(false);
    const menuRef = useRef<HTMLDivElement>(null);
    const escapeEdit = useRef<(() => boolean) | null>(null);
    const isMobile = useIsMobile();
    const textNoClick = useSlot(CONNECT_TEXT);
    const email = useSlot(CONNECT_EMAIL);
    const text = textNoClick.useTexting(open);
    const mailbox = email.useMailbox();
    const { mcp } = useChatContext();
    const ownerEmail = useOwnerEmail();
    const apps = text.apps;

    const close = () => setOpen(false);
    const ask = (message: string) => {
        close();
        onAsk(message);
    };

    let body;
    if (view === 'email') {
        body = (
            <>
                <MenuBackRow onBack={() => setView('menu')} title="Email" />
                <div className="px-2 pb-1.5 pt-4">
                    <email.View ownerEmail={ownerEmail} ask={ask} escape={escapeEdit} />
                </div>
            </>
        );
    } else if (view !== 'menu') {
        body = (
            <>
                <MenuBackRow onBack={() => setView('menu')} title={TEXT_APPS[view].label} />
                <div className="px-2 pb-1.5 pt-4">
                    <textNoClick.View app={view} texting={text} />
                </div>
            </>
        );
    } else {
        const more = <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground/70" />;
        body = (
            // eslint-disable-next-line jsx-a11y/no-static-element-interactions -- arrow keys move between the items
            <div ref={menuRef} onKeyDown={(event: KeyboardEvent) => moveBetweenMenuItems(menuRef.current, event)}>
                <p className="px-3 pb-1.5 pt-1 text-[12.5px] text-muted-foreground">The same conversation, from anywhere</p>
                {apps.map((app) => {
                    const icon = <WayTile way={app} />;
                    // A phone opens the app itself; a laptop shows the code to scan with one.
                    if (isMobile) {
                        const href = text.hrefFor(app);
                        return (
                            <MenuItem
                                key={app}
                                icon={icon}
                                title={TEXT_APPS[app].label}
                                detail={GLOSS[app]}
                                href={href ?? undefined}
                                disabled={!href}
                                trailing={!href && <Loader2 className="h-4 w-4 shrink-0 animate-spin text-muted-foreground" />}
                                onSelect={() => {
                                    text.pick(app);
                                    close();
                                }}
                            />
                        );
                    }
                    return (
                        <MenuItem
                            key={app}
                            icon={icon}
                            title={TEXT_APPS[app].label}
                            detail={GLOSS[app]}
                            trailing={more}
                            onSelect={() => {
                                text.pick(app);
                                setView(app);
                            }}
                        />
                    );
                })}
                <MenuItem
                    icon={<WayTile way="email" />}
                    title="Email"
                    detail={mailbox?.paused ? 'Off' : (mailbox?.address ?? 'Write from your inbox')}
                    trailing={more}
                    onSelect={() => setView('email')}
                />
                <MenuItem
                    icon={<WayTile way="mcp" />}
                    title="MCP"
                    detail="Use it in Claude, ChatGPT, Cursor"
                    onSelect={() => {
                        close();
                        setMcpOpen(true);
                    }}
                />
            </div>
        );
    }

    return (
        <>
            <Popover
                open={open}
                onOpenChange={(next) => {
                    setOpen(next);
                    if (!next) return;
                    setView('menu');
                    // Its address is picked in the conversation, and mail to it turned on or off on another device,
                    // after this page read it.
                    email.refresh();
                }}
            >
                <PopoverTrigger asChild>
                    <button type="button" className={TRIGGER} data-testid="connect-menu-button">
                        <span className="flex items-center py-1 pl-1" aria-hidden="true">
                            {WAYS.map((way, i) => (
                                <WayTile
                                    key={way}
                                    way={way}
                                    className={cn(
                                        'h-[22px] w-[22px] rounded-[7px] ring-2 ring-background transition-transform duration-200 ease-out motion-reduce:transition-none',
                                        i > 0 && '-ml-2',
                                        FAN[i]
                                    )}
                                />
                            ))}
                        </span>
                        {/* A phone's bar shares its row with the page's other actions: the apps say it there. */}
                        <span className={isMobile ? 'sr-only' : undefined}>Connect</span>
                        <ChevronDown className="h-3.5 w-3.5 text-muted-foreground transition-transform duration-200 group-data-[state=open]:rotate-180" />
                    </button>
                </PopoverTrigger>
                <PopoverContent
                    side="bottom"
                    align={align}
                    sideOffset={8}
                    collisionPadding={12}
                    data-testid="connect-menu"
                    className={cn('w-[384px] max-w-[calc(100vw-24px)]', MENU_PANEL)}
                    onEscapeKeyDown={(event) => {
                        // Escape cancels an edit, then steps back out of a detail, before it closes the menu.
                        if (escapeEdit.current?.()) {
                            event.preventDefault();
                            return;
                        }
                        if (view !== 'menu') {
                            event.preventDefault();
                            setView('menu');
                        }
                    }}
                >
                    {body}
                </PopoverContent>
            </Popover>
            <MCPSetupModal
                open={mcpOpen}
                onClose={() => setMcpOpen(false)}
                url={mcp?.url ?? MCP_URL}
                serverName="noclick"
                title="Connect over MCP"
                intro={mcp?.intro ?? MCP_INTRO}
            />
        </>
    );
}

/** The signed-in person's email, as the console context names it (null where it names none). */
function useOwnerEmail(): string | null {
    return useContext(ConsoleContext)?.user.email ?? null;
}
