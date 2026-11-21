// What stands in Connections' slots (./slots.ts) when no host fills them: the platform API's connections and catalog,
// connecting at NoClick's connect page in a new tab, and an account's access said in words.
import { useContext, useEffect, useMemo, type ReactNode } from 'react';
import { ArrowUpRight } from 'lucide-react';
import { Connection, type NoClick } from 'noclick';
import { toast } from 'sonner';
import { useSlot } from '@/slots';
import { useClient } from '@/sdk/client';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import { ConsoleContext } from '@/screens/console/hooks/useConsole';
import { connectionUrl, NOCLICK_SITE } from '@/screens/console/lib/site';
import { ownerOnlyWhy } from '@/screens/console/ownerOnly';
import { errorText } from '@/screens/console/pages/resources/shared';
import { Section } from '@/screens/resources/ui';
import { BrandIcon } from '@/ui/BrandIcon';
import { BUTTON_SECONDARY } from '@/ui/buttons';
import { connectByLink } from '@/ui/connectStandards';
import { CONNECT_APP, CONNECT_MODEL, CONNECTION_MARK } from '@/ui/slots';
import { cn } from '@/ui/utils';
import { CONNECTIONS_READ } from './apiAccounts';
import { useConnectionsContext } from './context';
import { sortedAccounts, type CatalogApp, type ConnectedAccount } from './model';
import { ConnectionsAccountsContext, useAccountMaker, type ConnectionsAccounts } from './reads';
import type { AiCompanyEntry, AiConnectProps } from './slots';

const sentence = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);
const words = (name: string) => sentence(name.replace(/[_-]+/g, ' ').trim());

/** Every connection the platform API lists in the workspace the page shows, both those connected in the NoClick app and
 *  the named ones code made (one still waiting for its account is left out); read again when one is connected here. */
export function ApiReads({ children }: { children: ReactNode }) {
    const client = useClient();
    const team = useConnectionsContext().teamWorkspace ?? undefined;
    const { data: connections, error, refresh } = useV1(`${CONNECTIONS_READ}&team=${team ?? ''}`, () => Connection.list({ client, organizationId: team }), { client });
    const make = useAccountMaker();
    const { subscribe } = useSlot(CONNECT_APP);
    useEffect(() => subscribe?.(() => invalidateV1(CONNECTIONS_READ)), [subscribe]);
    const value = useMemo<ConnectionsAccounts>(() => {
        const retry = () => void refresh();
        if (!connections) return { accounts: [], loaded: false, error: error ? errorText(error) : null, retry };
        return { accounts: sortedAccounts(connections.filter((c) => c.status !== 'pending').map(make)), loaded: true, error: null, retry };
    }, [connections, error, refresh, make]);
    return <ConnectionsAccountsContext.Provider value={value}>{children}</ConnectionsAccountsContext.Provider>;
}

/** The apps whose accounts connect at a connect page: the integrations the platform API lists, each named as it names
 *  them (one only bought, a phone number, is left out). */
export function useV1CatalogApps(): CatalogApp[] {
    const client = useClient();
    const read = useV1('connections:integrations:app', () => Connection.integrations(undefined, { client, kind: 'app' }), { client });
    return useMemo(
        () =>
            (read.data ?? [])
                .filter((i) => i.credentialTypes.length > 0 && i.connectWith.some((way) => way !== 'purchase'))
                .map((i): CatalogApp => ({
                    value: `automation-${i.name.replace(/_/g, '-')}`,
                    label: i.label ?? words(i.name),
                    acceptedCredentialTypes: i.credentialTypes,
                    primaryCredentialType: i.credentialTypes[0],
                    listed: true,
                })),
        [read.data]
    );
}

/** Connects another account of `app` at its connect page on NoClick, in a new tab opened as it's asked for; the
 *  accounts are read again once it lands. */
export function connectInNewTab(app: CatalogApp, client: NoClick): void {
    const integration = app.value.replace(/^automation-/, '').replace(/-/g, '_');
    void connectByLink(client, integration, app.primaryCredentialType).then(
        () => {
            invalidateV1(CONNECTIONS_READ);
            toast.success(`${app.label} connected`);
        },
        (error: unknown) => toast(`Couldn’t connect ${app.label}`, { description: errorText(error) })
    );
}

/** A model provider's mark: its AI glyph where the marks know one, else its service's mark. */
function CompanyMark({ credentialType }: { credentialType: string }) {
    const marks = useSlot(CONNECTION_MARK);
    const glyph = marks.aiGlyph(credentialType);
    return (
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-foreground/[0.05]">
            {glyph ? <BrandIcon Icon={glyph.Icon} iconColor={glyph.iconColor} className="h-[22px] w-[22px]" /> : <marks.Mark credentialType={credentialType} size="sm" />}
        </span>
    );
}

/** The model providers the platform API knows, one tile each. */
export function useModelCompanies(): AiCompanyEntry[] {
    const client = useClient();
    const read = useV1('connections:integrations:model', () => Connection.integrations(undefined, { client, kind: 'model' }), { client });
    return useMemo(
        () =>
            (read.data ?? [])
                .filter((i) => i.credentialTypes.length > 0)
                .map((i): AiCompanyEntry => {
                    const title = i.label ?? words(i.name);
                    return {
                        id: i.name,
                        title,
                        line: i.subscription ? 'Plan or API key' : undefined,
                        credentialTypes: i.credentialTypes,
                        searchFields: [title, i.name],
                        mark: <CompanyMark credentialType={i.credentialTypes[0]} />,
                    };
                }),
        [read.data]
    );
}

/** Connecting an AI account at its connect page on NoClick, through the shared `connect.model` slot. */
export function ModelCompanyConnect({ company, onOpenChange }: AiConnectProps) {
    const client = useClient();
    const ModelConnect = useSlot(CONNECT_MODEL);
    return (
        <ModelConnect
            credentialType={company?.credentialTypes[0] ?? null}
            integration={company?.id ?? null}
            title={company ? `Connect ${company.title}` : undefined}
            others={[]}
            client={client}
            onOpenChange={onOpenChange}
            onConnected={() => invalidateV1(CONNECTIONS_READ)}
        />
    );
}

/** Whose an account is, in words: an account shared with you names who shared it; your own says who else may use it is
 *  chosen on NoClick, with the way there. */
export function ReadOnlyAccess({ account }: { account: ConnectedAccount; onLeft: () => void }) {
    const site = useContext(ConsoleContext)?.site ?? NOCLICK_SITE;
    const { credential } = account;
    if (account.source !== 'connected') {
        const sharer = credential.shared_by_name || credential.shared_by_email;
        return (
            <Section title="Access">
                <p className="text-[14px] leading-relaxed text-muted-foreground">
                    {account.source === 'organization'
                        ? 'It belongs to your organization, and its owner looks after it.'
                        : `${sharer ?? 'A teammate'} shared it with you${credential.shared_by_email && credential.shared_by_name ? ` (${credential.shared_by_email})` : ''}. They look after it.`}
                </p>
            </Section>
        );
    }
    return (
        <Section
            title="Access"
            action={
                <a href={connectionUrl(site, credential.id)} target="_blank" rel="noopener noreferrer" className={cn(BUTTON_SECONDARY, 'h-8 px-3.5 text-[13px]')}>
                    Share on NoClick
                    <ArrowUpRight className="h-3.5 w-3.5" />
                </a>
            }
        >
            <p className="text-[14px] leading-relaxed text-muted-foreground">{ownerOnlyWhy('connectionSharing')}</p>
        </Section>
    );
}
