// The chat's Connect button: the other ways into this same conversation. WhatsApp and iMessage show a code to scan
// (on a phone, open the app itself), carrying the message that links the phone until one is; email shows NoClick's
// own address (claimed the first time it's opened, renamed in place, and taking mail or not as its owner says); MCP
// opens the setup guides for using NoClick from an AI client.
import { useEffect, useRef, useState, type KeyboardEvent, type MutableRefObject } from 'react';
import { useRouteLoaderData } from 'react-router';
import { ArrowUpRight, Check, ChevronDown, ChevronRight, Copy, Loader2, PenLine } from 'lucide-react';
import { MCP } from '@lobehub/icons';
import { IoMail } from 'react-icons/io5';
import { QrCode, QrPlaceholder } from '~/components/shared/QrCode';
import { Popover, PopoverContent, PopoverTrigger } from '~/components/ui/popover';
import { Skeleton } from '~/components/ui/skeleton';
import { Switch } from '~/components/ui/switch';
import { NoClickMCPSetupModal } from '~/components/workflow/MCPConnectModal';
import { ensureCoordinatorEmail, refreshCoordinatorReach, renameCoordinatorEmail, setCoordinatorEmailInbound, useCoordinatorReach } from '~/hooks/useCoordinatorChat';
import { useIsMobile } from '~/hooks/useIsMobile';
import { TEXT_APP_ORDER, useTextNoClick } from '~/hooks/useTextNoClick';
import { formatPhoneForDisplay } from '~/lib/phoneFormat';
import { cn } from '~/lib/utils';
import { AppTile, ChannelTile } from './AppTile';
import { BUTTON_GHOST, BUTTON_PRIMARY, BUTTON_SECONDARY } from './buttons';
import { FIELD } from './fields';
import { MENU_PANEL, MenuBackRow, MenuItem, moveBetweenMenuItems } from './ComposerAddMenu';
import { mailLink } from './mailApp';
import { TEXT_APPS, type TextApp } from './textApp';

type View = 'menu' | TextApp | 'email';
type Way = TextApp | 'email' | 'mcp';

// Email in Mail's blue and MCP on graphite, beside the texting apps' own tiles.
const McpGlyph = ({ className }: { className?: string }) => <MCP className={className} />;
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
    'group inline-flex h-9 items-center gap-2 rounded-full bg-background pl-1 pr-2.5 text-[14px] font-medium text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';
const WAYS: Way[] = ['whatsapp', 'imessage', 'email', 'mcp'];
const FAN = [
    '-rotate-[8deg] group-hover:-translate-x-[3px] group-hover:-rotate-[12deg] group-data-[state=open]:-translate-x-[3px] group-data-[state=open]:-rotate-[12deg]',
    '-rotate-[3deg] group-hover:-translate-x-px group-hover:-rotate-[4deg] group-data-[state=open]:-translate-x-px group-data-[state=open]:-rotate-[4deg]',
    'rotate-[3deg] group-hover:translate-x-px group-hover:rotate-[4deg] group-data-[state=open]:translate-x-px group-data-[state=open]:rotate-[4deg]',
    'rotate-[8deg] group-hover:translate-x-[3px] group-hover:rotate-[12deg] group-data-[state=open]:translate-x-[3px] group-data-[state=open]:rotate-[12deg]',
];
const QUIET_LINK =
    'inline-flex items-center gap-0.5 rounded-md text-[13px] text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';
const GLOSS: Record<TextApp, string> = { whatsapp: 'Text it from your phone', imessage: 'Text it from your iPhone' };
const ASK_TO_NAME = 'Pick a better name for your email address.';
const ASK_TO_ADD_EMAIL = 'I want to add my email address to this account.';
const SMALL = 'h-8 px-3.5 text-[13px]';
const PILL = cn(BUTTON_SECONDARY, 'h-8 gap-1.5 px-3 text-[13px]');

/** NoClick's address: claimed the first time this opens, copied, renamed in place; asking NoClick to name it is the
 *  quiet alternative. Its owner can turn mail to it off (`paused`) and keep the address; `fromAnyone`: anyone's mail
 *  reaches it, else only the owner's. `escape` lets Escape cancel an edit before it steps back out of the detail. */
function EmailDetail({
    address,
    paused,
    fromAnyone,
    ownerEmail,
    onAsk,
    escape,
}: {
    address: string | null | undefined;
    paused: boolean;
    fromAnyone: boolean;
    ownerEmail?: string;
    onAsk: (text: string) => void;
    escape: MutableRefObject<(() => boolean) | null>;
}) {
    const [claim, setClaim] = useState<'claiming' | 'unavailable' | 'failed' | null>(null);
    const [claimError, setClaimError] = useState('');
    const [draft, setDraft] = useState<string | null>(null);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState('');
    const [copied, setCopied] = useState(false);
    const [switchError, setSwitchError] = useState('');
    const [local, domain] = address ? [address.split('@')[0], address.split('@')[1]] : ['', ''];
    // Nothing to compose to an address that ignores its mail.
    const mail = address && ownerEmail && !paused ? mailLink(address, ownerEmail) : null;
    const takeMail = (on: boolean) => {
        setSwitchError('');
        setCoordinatorEmailInbound(on).catch((e: unknown) => setSwitchError(e instanceof Error ? e.message : 'Could not change it'));
    };
    const copy = () => {
        if (!address) return;
        void navigator.clipboard.writeText(address).then(() => {
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
        });
    };

    const tryClaim = () => {
        setClaim('claiming');
        ensureCoordinatorEmail().then(
            (claimed) => setClaim(claimed ? null : 'unavailable'),
            (e: unknown) => {
                setClaimError(e instanceof Error ? e.message : 'Could not get an address');
                setClaim('failed');
            }
        );
    };
    // A reach that has loaded without an address gets one; until it loads there's nothing to decide.
    useEffect(() => {
        if (address === null && claim === null) tryClaim();
        // eslint-disable-next-line react-hooks/exhaustive-deps -- once per address that's missing
    }, [address]);

    const cancel = () => {
        setDraft(null);
        setError('');
    };
    useEffect(() => {
        escape.current = () => {
            if (draft === null) return false;
            cancel();
            return true;
        };
        return () => {
            escape.current = null;
        };
    }, [draft, escape]);

    const save = async () => {
        const name = (draft ?? '').trim().toLowerCase();
        if (!name || name === local) return cancel();
        setSaving(true);
        try {
            await renameCoordinatorEmail(name);
            cancel();
        } catch (e) {
            setError(e instanceof Error ? e.message : 'Could not change the address');
        } finally {
            setSaving(false);
        }
    };

    if (claim === 'unavailable') return <p className="text-[13.5px] leading-relaxed text-muted-foreground">Email isn’t set up on this instance.</p>;
    if (claim === 'failed') {
        return (
            <>
                <p className="text-[13.5px] leading-relaxed text-muted-foreground">{claimError}</p>
                <button type="button" className={cn(BUTTON_GHOST, SMALL, '-ml-3 mt-2')} onClick={tryClaim}>
                    Try again
                </button>
            </>
        );
    }
    if (!address) return <Skeleton className="h-10 w-full rounded-xl" />;

    return (
        <>
            {draft === null ? (
                <>
                    {/* Never cut short: a long name wraps, at the @ where it can. */}
                    <p className="m-0 select-all text-[16px] font-medium leading-snug text-foreground [overflow-wrap:anywhere]" data-testid="connect-email-address">
                        {local}
                        <wbr />@{domain}
                    </p>
                    <div className="mt-3 flex flex-wrap items-center gap-1.5">
                        <button type="button" className={PILL} onClick={copy}>
                            {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
                            {copied ? 'Copied' : 'Copy'}
                        </button>
                        <button type="button" className={PILL} onClick={() => setDraft(local)}>
                            <PenLine className="h-3.5 w-3.5" />
                            Change
                        </button>
                        {mail && (
                            <a href={mail.href} {...(mail.web ? { target: '_blank', rel: 'noopener noreferrer' } : {})} className={PILL}>
                                <ArrowUpRight className="h-3.5 w-3.5" />
                                Open {mail.label}
                            </a>
                        )}
                    </div>
                </>
            ) : (
                <form
                    onSubmit={(e) => {
                        e.preventDefault();
                        void save();
                    }}
                >
                    <div className={cn(FIELD, 'flex items-center gap-0 pr-3 focus-within:border-foreground/25')}>
                        <input
                            // eslint-disable-next-line jsx-a11y/no-autofocus -- Change opened it to be typed in
                            autoFocus
                            value={draft}
                            onChange={(e) => {
                                setDraft(e.target.value);
                                setError('');
                            }}
                            aria-label="Address name"
                            aria-invalid={!!error}
                            spellCheck={false}
                            autoCapitalize="none"
                            className="h-full min-w-0 flex-1 bg-transparent text-[14px] text-foreground outline-none"
                        />
                        <span className="shrink-0 text-[14px] text-muted-foreground">@{domain}</span>
                    </div>
                    {error && (
                        <p role="alert" className="mt-1.5 text-[12.5px] text-red-600 dark:text-red-400">
                            {error}
                        </p>
                    )}
                    <div className="mt-2.5 flex items-center gap-1.5">
                        <button type="submit" disabled={saving} className={cn(BUTTON_PRIMARY, SMALL)}>
                            {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : 'Save'}
                        </button>
                        <button type="button" className={cn(BUTTON_GHOST, SMALL)} onClick={cancel}>
                            Cancel
                        </button>
                    </div>
                </form>
            )}
            {fromAnyone || ownerEmail ? (
                <div className="mt-4">
                    <div className="flex items-center justify-between gap-3">
                        <label htmlFor="connect-email-inbound" className="min-w-0 text-[13.5px] leading-snug text-foreground">
                            Answer emails
                        </label>
                        <Switch
                            id="connect-email-inbound"
                            checked={!paused}
                            onCheckedChange={takeMail}
                            className="data-[state=unchecked]:bg-input dark:data-[state=unchecked]:bg-input"
                        />
                    </div>
                    <p className="mt-1 text-[13px] leading-relaxed text-muted-foreground [overflow-wrap:anywhere]" data-testid="connect-email-inbound-note">
                        {paused
                            ? 'Mail to this address is ignored. The address stays yours.'
                            : !fromAnyone
                              ? `Email it from ${ownerEmail} and it replies on the same thread. Mail from other addresses is ignored.`
                              : ownerEmail
                                ? `Anyone can email it, and it replies on the same thread. Mail from ${ownerEmail} shows here too.`
                                : 'Anyone can email it, and it replies on the same thread.'}
                    </p>
                    {switchError && (
                        <p role="alert" className="mt-1.5 text-[12.5px] text-red-600 dark:text-red-400">
                            {switchError}
                        </p>
                    )}
                </div>
            ) : (
                <p className="mt-3 text-[13px] leading-relaxed text-muted-foreground">It reads mail from your account’s email, and this account doesn’t have one yet.</p>
            )}
            <div className="mt-2.5 flex items-center gap-4">
                {!ownerEmail && (
                    <button type="button" className={QUIET_LINK} onClick={() => onAsk(ASK_TO_ADD_EMAIL)}>
                        Add your email
                    </button>
                )}
                <button type="button" className={QUIET_LINK} onClick={() => onAsk(ASK_TO_NAME)}>
                    Ask NoClick to name it
                </button>
            </div>
        </>
    );
}

/** `onAsk` drafts a message to NoClick, for what it sets up itself (its own email address). */
export function ConnectMenu({ align = 'start', onAsk }: { align?: 'start' | 'end'; onAsk: (text: string) => void }) {
    const [open, setOpen] = useState(false);
    const [view, setView] = useState<View>('menu');
    const [mcpOpen, setMcpOpen] = useState(false);
    const menuRef = useRef<HTMLDivElement>(null);
    const escapeEdit = useRef<(() => boolean) | null>(null);
    const isMobile = useIsMobile();
    const reach = useCoordinatorReach();
    const text = useTextNoClick(open);
    const ownerEmail = (useRouteLoaderData('routes/dashboard') as { user?: { email?: string } } | undefined)?.user?.email;
    // The app most people where you are use first, as the sidebar's card offers it.
    const apps = [text.app, ...TEXT_APP_ORDER.filter((app) => app !== text.app)].filter((app) => text.offered.includes(app));

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
                    <EmailDetail
                        address={reach ? reach.email : undefined}
                        paused={!!reach?.email_paused}
                        fromAnyone={!!reach?.email_from_anyone}
                        ownerEmail={ownerEmail}
                        onAsk={ask}
                        escape={escapeEdit}
                    />
                </div>
            </>
        );
    } else if (view !== 'menu') {
        const { label, app: appName } = TEXT_APPS[view];
        const href = text.hrefFor(view);
        const number = text.numbers[view] ?? '';
        body = (
            <>
                <MenuBackRow onBack={() => setView('menu')} title={label} />
                <div className="px-2 pb-1.5 pt-4">
                    {href ? (
                        <QrCode
                            value={href}
                            label={`Scan to message NoClick on ${label} at ${formatPhoneForDisplay(number)}`}
                            mark={<ChannelTile channel={view} />}
                            className="mx-auto w-full max-w-[208px]"
                        />
                    ) : (
                        <QrPlaceholder label="Getting a fresh code" className="mx-auto w-full max-w-[208px]" />
                    )}
                    <p className="mx-auto mt-3 max-w-[300px] text-center text-[13px] leading-relaxed text-muted-foreground">
                        {text.linked ? 'Scan to open the chat on your phone.' : 'Scan with your phone’s camera. The message it opens links your phone to NoClick.'}
                    </p>
                    <div className="mt-4 flex items-center justify-between gap-3">
                        <span className="text-[13px] tabular-nums text-muted-foreground">{formatPhoneForDisplay(number)}</span>
                        {href && (
                            <a href={href} target="_blank" rel="noopener noreferrer" className={QUIET_LINK}>
                                Open {appName}
                                <ArrowUpRight className="h-3.5 w-3.5" />
                            </a>
                        )}
                    </div>
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
                    detail={reach?.email_paused ? 'Off' : (reach?.email ?? 'Write from your inbox')}
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
                    refreshCoordinatorReach();
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
                        Connect
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
            <NoClickMCPSetupModal open={mcpOpen} onClose={() => setMcpOpen(false)} />
        </>
    );
}
