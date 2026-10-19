// A connected account as Connections shows it: the app it signs in to, the
// account itself in words you'd recognise, whose it is, and what (if anything)
// keeps it from working. Joins the credential list with the app catalog.
import { useMemo } from 'react';
import type { CredentialInfo } from '~/types/socket-events.generated';
import type { ServiceCredentialOption } from '~/utils/credentialTypes';
import { hasCustomCredentialForm } from '~/components/workflow/customCredentialForms';
import { useServiceCredentialOptions } from '~/hooks/useServiceCredentialOptions';
import { revokedReasonLabel } from '~/lib/credentialAccess';
import { describeAccount } from './accountNames';

/** Which tab an account lives on: yours, your organization's, or shared with you. */
export type AccountSource = 'connected' | 'organization' | 'shared';

export interface ConnectedAccount {
    credential: CredentialInfo;
    /** The catalog app it signs in to; absent for model sign-ins, env bundles and MCP servers. */
    service?: ServiceCredentialOption;
    /** What the account is, in a word: the app, else the kind of key. */
    app: string;
    /** The account itself: its email or login, its variables, else its name or when it was added. */
    line: string;
    source: AccountSource;
    /** What keeps it from working, when something is known to. */
    problem?: string;
}

/** Apps whose accounts connect from the catalog; the rest (an agent's model key, an MCP server) connect from a node. */
export function useCatalogServices(): ServiceCredentialOption[] {
    const all = useServiceCredentialOptions();
    return useMemo(() => all.filter((s) => !hasCustomCredentialForm(s.value)), [all]);
}

export function accountSource(credential: CredentialInfo): AccountSource {
    if (credential.access_type === 'owner') return 'connected';
    if (credential.access_type === 'shared_org') return 'organization';
    return 'shared';
}

export function accountProblem(credential: CredentialInfo): string | undefined {
    if (credential.revoked_at) {
        const reason = revokedReasonLabel(credential.revoked_reason);
        return reason && reason !== 'disconnected' ? `Disconnected: ${reason}` : 'Disconnected';
    }
    if (credential.connection_healthy === false) return credential.connection_hint || 'The connection dropped';
    if (credential.over_cap) return 'Over your plan’s limit for this app';
    return undefined;
}

/** Every account you can use, the broken ones first, then by app and account. */
export function useConnectedAccounts(credentials: CredentialInfo[]): ConnectedAccount[] {
    const services = useCatalogServices();
    return useMemo(() => {
        const byType = new Map<string, ServiceCredentialOption>();
        for (const service of services) {
            for (const type of service.acceptedCredentialTypes) if (!byType.has(type)) byType.set(type, service);
        }
        return credentials
            .map((credential): ConnectedAccount => {
                const service = byType.get(credential.credential_type);
                return { credential, service, ...describeAccount(credential, service?.label), source: accountSource(credential), problem: accountProblem(credential) };
            })
            .sort((a, b) => Number(!a.problem) - Number(!b.problem) || a.app.localeCompare(b.app) || a.line.localeCompare(b.line));
    }, [credentials, services]);
}
