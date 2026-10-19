// The AI companies people connect for their agents: every company the agent
// credential model knows (`agentCompanies`), each with the ways this instance can
// connect it, the subscription sign-ins it reports and an API key. A company's
// dialog (AiProviderDialog) runs the same sign-in and key logic the agent node's
// credential panel uses, so an account added here is the one an agent picks up.
import { useMemo, type ComponentType } from 'react';
import { Github, GithubCopilot } from '@lobehub/icons';
import { BrandIcon } from '~/components/shared/BrandIcon';
import { hasAgentOAuthConnect } from '~/components/workflow/AgentOAuthConnect';
import { useInstanceCapabilities } from '~/hooks/useInstanceCapabilities';
import { CLI_MODEL_PROVIDER } from '~/lib/agentChat';
import {
    AGENT_OAUTH_PROVIDER_KEY,
    AGENT_SIGN_IN_NAMES,
    acceptedAgentCredentialTypes,
    agentCompanies,
    getAgentCredentialType,
    isSignInOnlyAgentProvider,
    type AgentCompany,
} from '~/lib/agentCredentialModel';
import { cn } from '~/lib/utils';
import { getProviderMetadata, providerGlyph, ModelProvider } from '~/types/provider';
import { getCredentialIcon } from '~/utils/credentialIcons';

export interface AiCompany extends AgentCompany {
    /** The subscription sign-ins this instance offers for it, as credential types. */
    signIns: string[];
    /** The providers a pasted key is saved as, one per distinct key. */
    keys: ModelProvider[];
    /** Every credential type that counts as one of its accounts. */
    credentialTypes: string[];
    /** The subscription it signs in with, for its tile ("Claude subscription"); empty for a key-only company, whose
     *  tile, like an app's, is just its name. */
    line: string;
    /** What it gives your agents, for its page. */
    uses: string;
}

const list = (parts: string[]) => new Intl.ListFormat('en', { type: 'conjunction' }).format(parts);

function describe(company: AgentCompany, signIns: string[]): { line: string; uses: string } {
    const subscriptions = signIns.map((type) => AGENT_SIGN_IN_NAMES[type]?.subscription).filter((name): name is string => !!name);
    const line = subscriptions.length ? `${list(subscriptions)} subscription` : '';
    // A harness or a sign-in-only product (Copilot) is named as itself, the company's own model API by its models.
    const harnesses = new Set<string>(Object.values(CLI_MODEL_PROVIDER));
    const parts = company.members.map((member) => {
        const title = getProviderMetadata(member)?.title ?? member;
        return !harnesses.has(member) && !isSignInOnlyAgentProvider(member) && title === company.title ? `${title} models` : title;
    });
    return { line, uses: `${list(parts)} for your agents.` };
}

/** The AI companies this instance can connect, in the credential model's order; one it has no way to connect is left out. */
export function useAiCompanies(): AiCompany[] {
    const { agentSignIns } = useInstanceCapabilities();
    return useMemo(
        () =>
            agentCompanies().flatMap((company): AiCompany[] => {
                const signIns = [
                    ...new Set(
                        company.members
                            .map((member) => AGENT_OAUTH_PROVIDER_KEY[member])
                            .map((key) => (key ? agentSignIns[key] : undefined))
                            .filter((type): type is string => !!type && hasAgentOAuthConnect(type))
                    ),
                ];
                const keyOf = (member: ModelProvider) => (getProviderMetadata(member)?.requiredApiKeys?.[0] ?? []).join('+');
                const keys = company.members.filter(
                    (member, i, all) => !isSignInOnlyAgentProvider(member) && !!keyOf(member) && all.findIndex((other) => !isSignInOnlyAgentProvider(other) && keyOf(other) === keyOf(member)) === i
                );
                if (!signIns.length && !keys.length) return [];
                const credentialTypes = [...new Set(company.members.flatMap((member) => acceptedAgentCredentialTypes(member)))];
                return [{ ...company, signIns, keys, credentialTypes, ...describe(company, signIns) }];
            }),
        [agentSignIns]
    );
}

type Glyph = ComponentType<{ className?: string }>;

// GitHub's two model sources run through OpenCode, whose mark their metadata
// borrows for the model picker; as accounts they're GitHub.
const ACCOUNT_MARKS: Partial<Record<ModelProvider, Glyph>> = {
    [ModelProvider.GITHUB_COPILOT]: GithubCopilot,
    [ModelProvider.GITHUB_MODELS]: Github,
};

/** An agent credential type's brand mark: its registered icon, else its provider's glyph. */
export function agentMark(credentialType: string): { Icon: Glyph; iconColor: string } | undefined {
    if (!credentialType.startsWith('agent_')) return undefined;
    const registered = getCredentialIcon(credentialType);
    if (registered.hasServiceIcon) return { Icon: registered.Icon, iconColor: registered.iconColor };
    const provider = credentialType.replace(/^agent_/, '').replace(/_oauth$/, '') as ModelProvider;
    const Icon = ACCOUNT_MARKS[provider] ?? providerGlyph(provider);
    return Icon ? { Icon, iconColor: '' } : undefined;
}

/** A company's mark: its own provider's. */
export function AiMark({ provider, size = 'md' }: { provider: ModelProvider; size?: 'md' | 'lg' }) {
    const mark = agentMark(getAgentCredentialType(provider));
    return (
        <span className={cn('grid shrink-0 place-items-center bg-foreground/[0.05]', size === 'lg' ? 'h-12 w-12 rounded-2xl ring-1 ring-inset ring-foreground/[0.06]' : 'h-10 w-10 rounded-xl')}>
            {mark && <BrandIcon Icon={mark.Icon} iconColor={mark.iconColor} className={size === 'lg' ? 'h-6 w-6' : 'h-[22px] w-[22px]'} />}
        </span>
    );
}
