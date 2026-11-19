// What the box's "+" can point a message at (`ComposerSources`, @/ui/chat/ComposerAddMenu), read through the platform
// API: every automation the account can open, the most recently changed first, each in the mark of what it's made of;
// and the account's own accounts that are connected, named connections and those connected in the app alike, the most
// recently connected first, each named and marked as the host names accounts (the `connection.mark` slot). A message
// names a named connection by its connection's id and one connected in the app by its credential's, as the API finds
// each (lib/agentThread/messages.ts).
import { useMemo } from 'react';
import { Connection, Workflow } from 'noclick';
import { relativeShort } from '@/lib/formatters';
import { NAMED_CONNECTION } from '@/lib/agentThread/messages';
import { useV1 } from '@/sdk/useV1';
import { BrandIcon } from '@/ui/BrandIcon';
import { MENU_LOGO, type AccountChoice, type AutomationChoice, type ComposerSources } from '@/ui/chat/ComposerAddMenu';
import { useConnectionMarks } from '@/ui/connectionMark';
import { NodeMark } from '@/ui/primitives';
import { useWorkClient } from '../client';

const APP_REF = 'credential:';
const ADDED = /^Added /;
const iso = (at: Date | null) => at?.toISOString() ?? null;

function useAutomations() {
    const client = useWorkClient();
    const read = useV1('work:composer:automations', () => Workflow.list({ client }), { client });
    const automations = useMemo(
        () =>
            (read.data ?? [])
                .map((w): AutomationChoice => {
                    const type = w.stepTypes[0];
                    return { id: w.id, name: w.name, updatedAt: iso(w.updatedAt) ?? undefined, mark: type ? <NodeMark type={type} size="md" /> : undefined };
                })
                .sort((a, b) => (b.updatedAt ?? '').localeCompare(a.updatedAt ?? '')),
        [read.data]
    );
    return { automations, loading: read.loading };
}

function useAccounts(): { accounts: AccountChoice[]; loaded: boolean } {
    const client = useWorkClient();
    const marks = useConnectionMarks();
    const read = useV1('work:composer:accounts', () => Connection.list({ client }), { client });
    const accounts = useMemo(
        () =>
            (read.data ?? [])
                .filter((c) => c.connected && c.credentialType)
                .map((c) => ({ c, at: iso(c.connectedAt ?? c.createdAt) }))
                .sort((a, b) => (b.at ?? '').localeCompare(a.at ?? ''))
                .map(({ c, at }): AccountChoice => {
                    const credentialType = c.credentialType as string;
                    const { app, line, aliases } = marks.account({ credentialType, integration: c.integration, name: c.name, account: c.account, connectedAt: at });
                    const { Icon, iconColor } = marks.accountGlyph({ credential_type: credentialType });
                    const id = c.id.startsWith(APP_REF) ? c.id.slice(APP_REF.length) : `${NAMED_CONNECTION}${c.id}`;
                    return {
                        id,
                        app,
                        line,
                        aliases,
                        name: c.name,
                        mark: <BrandIcon Icon={Icon} iconColor={iconColor} className={MENU_LOGO} />,
                        // A line that only says when it was connected names nothing of the account.
                        reference: { kind: 'account', id, label: line === app || ADDED.test(line) ? app : `${app} · ${line}` },
                    };
                }),
        [read.data, marks]
    );
    return { accounts, loaded: read.data !== undefined || read.error !== undefined };
}

export const COMPOSER_SOURCES: ComposerSources = { useAutomations, useAccounts, when: relativeShort };
