// What stands in the Connect menu's texting and email slots: NoClick's own lines and address read through the platform
// API. A text reaches the account only from the owner's linked phone (one from any other phone starts an account of its
// own), so a line is offered to text only once a phone is linked, and otherwise the owner is sent to link one on
// NoClick. NoClick's address is read and its mail switched on or off; claiming or renaming it is asking NoClick.
import { useContext, useMemo } from 'react';
import { ArrowUpRight } from 'lucide-react';
import { Human, Inbox, NotFound } from 'noclick';
import { useClient } from '@/sdk/client';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import { ConsoleContext } from '@/screens/console/hooks/useConsole';
import { phoneSettingsUrl } from '@/screens/console/lib/site';
import { coordinatorAgent } from '@/screens/work/coordinatorAgent';
import { formatPhoneForDisplay } from '@/lib/phoneFormat';
import type { TextApp } from '@/ui/AppTile';
import { Skeleton } from '@/ui/skeleton';
import type { ConnectEmail, ConnectText, Mailbox, Texting } from '../slots';
import { useSite } from '../site';
import { EmailView } from './EmailView';
import { preferredTextApp, TEXT_APPS } from './textApp';

const QUIET_LINK =
    'inline-flex items-center gap-0.5 rounded-md text-[13px] text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';

const REACH = 'chat:owner-reach';
const MAILBOX = 'chat:mailbox';
const APPS: readonly TextApp[] = ['whatsapp', 'imessage'];

/** NoClick's lines and whether the owner's phone is linked, read as the menu opens. */
function useReach(open: boolean) {
    const client = useClient();
    return useV1(REACH, () => Human.owner({ client }).reach(), { enabled: open });
}

function useTexting(open: boolean): Texting {
    const reach = useReach(open).data;
    const country = useContext(ConsoleContext)?.country;
    return useMemo(() => {
        const numbers = new Map((reach?.lines ?? []).map((line) => [line.app, line.number]));
        const first = preferredTextApp(country, typeof navigator === 'undefined' ? '' : navigator.userAgent);
        const apps = [first, ...APPS.filter((app) => app !== first)].filter((app) => numbers.has(app));
        return {
            apps,
            hrefFor: (app) => {
                const number = numbers.get(app);
                return number && reach?.phoneLinked ? TEXT_APPS[app].href(number, null) : null;
            },
            pick: () => undefined,
        };
    }, [reach, country]);
}

function TextView({ app, texting }: { app: TextApp; texting: Texting }) {
    const reach = useReach(true);
    const site = useSite();
    const line = reach.data?.lines.find((l) => l.app === app);
    if (!reach.data) return <Skeleton className="h-10 w-full rounded-xl" />;
    if (!line) return <p className="text-[13.5px] leading-relaxed text-muted-foreground">NoClick has no {TEXT_APPS[app].label} line here.</p>;
    const href = texting.hrefFor(app);
    const number = formatPhoneForDisplay(line.number);
    return (
        <>
            <p className="m-0 text-[16px] font-medium tabular-nums text-foreground" data-testid="connect-text-number">
                {number}
            </p>
            <p className="mt-2 text-[13px] leading-relaxed text-muted-foreground">
                {href
                    ? `Text NoClick here from your linked phone: it’s this same conversation.`
                    : 'Link your phone to NoClick first. A text from a phone that isn’t linked starts an account of its own.'}
            </p>
            <div className="mt-3">
                {href ? (
                    <a href={href} target="_blank" rel="noopener noreferrer" className={QUIET_LINK}>
                        Open {TEXT_APPS[app].app}
                        <ArrowUpRight className="h-3.5 w-3.5" />
                    </a>
                ) : (
                    <a href={phoneSettingsUrl(site)} target="_blank" rel="noopener noreferrer" className={QUIET_LINK}>
                        Link your phone on NoClick
                        <ArrowUpRight className="h-3.5 w-3.5" />
                    </a>
                )}
            </div>
        </>
    );
}

export const textOnNoClick: ConnectText = { useTexting, View: TextView };

/** NoClick's own inbox (`coordinator`): its address, and whether its mail wakes NoClick. */
function useInbox() {
    const client = useClient();
    return useV1(MAILBOX, async () => {
        try {
            return await Inbox.fromName('coordinator', { client, user: null }).hydrate();
        } catch (error) {
            if (error instanceof NotFound) return null;
            throw error;
        }
    });
}

function useMailbox(): Mailbox | undefined {
    const inbox = useInbox().data;
    if (inbox === undefined) return undefined;
    return { address: inbox?.address ?? null, paused: !!inbox && inbox.agentId === null };
}

function EmailOnNoClick({ ownerEmail, ask, escape }: { ownerEmail: string | null; ask: (text: string) => void; escape: { current: (() => boolean) | null } }) {
    const client = useClient();
    const inbox = useInbox().data;
    return (
        <EmailView
            address={inbox === undefined ? undefined : (inbox?.address ?? null)}
            paused={!!inbox && inbox.agentId === null}
            fromAnyone={inbox?.senders === 'anyone'}
            ownerEmail={ownerEmail ?? undefined}
            onAsk={ask}
            escape={escape}
            actions={{
                // Its mail wakes NoClick, or nobody; the address stays the account's either way.
                setInbound: async (on) => {
                    if (!inbox) return;
                    await inbox.update({ agent: on ? coordinatorAgent(client) : null });
                    invalidateV1(MAILBOX);
                },
            }}
        />
    );
}

export const emailOnNoClick: ConnectEmail = { useMailbox, refresh: () => invalidateV1(MAILBOX), View: EmailOnNoClick };
