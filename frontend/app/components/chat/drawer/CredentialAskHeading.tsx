// A builder question that asks for an account, headed the way the chat's connect card is: whose account (its mark,
// "Connect Anthropic") and what it's for, in NoClick's words rather than the builder's phrasing of the question.
import { NodeMark } from '~/components/dashboard/primitives';
import { BrandIcon } from '~/components/shared/BrandIcon';
import { appNameOf } from '~/components/credential/credentialMethods';
import { connectDialogHeader } from '~/components/credential/connect/connectHeader';
import { agentMark } from '~/components/shell/connections/aiAccounts';
import type { InputRequest } from '~/components/workflow/workflowGeneratorMock';
import { agentCompanies, agentCredentialProvider } from '~/lib/agentCredentialModel';
import { getProviderMetadata } from '~/types/provider';

export function CredentialAskHeading({ input }: { input: InputRequest & { nodeType: string } }) {
    const provider = input.nodeType === 'agent' ? agentCredentialProvider(input.credentialType) : null;
    // An agent's account is with a company, as Connections lists it: Claude Code's is Anthropic's.
    const name = provider
        ? agentCompanies().find((company) => company.members.includes(provider))?.title ?? getProviderMetadata(provider)?.title ?? provider
        : appNameOf(input.nodeType);
    const ai = provider && input.credentialType ? agentMark(input.credentialType) : undefined;
    const line = input.description || (provider ? 'The AI this agent thinks with, on your own account.' : connectDialogHeader(name, 'connect').description);
    return (
        <header className="mb-4 flex items-start gap-3" data-testid="credential-ask-heading">
            <span className="mt-0.5 shrink-0">
                {provider ? ai && <BrandIcon Icon={ai.Icon} iconColor={ai.iconColor} className="h-5 w-5" /> : <NodeMark type={input.nodeType} size="md" />}
            </span>
            <div className="min-w-0">
                <h3 className="text-[14.5px] font-medium leading-snug tracking-[-0.005em] text-foreground">Connect {name}</h3>
                <p className="mt-0.5 text-[13px] leading-snug text-muted-foreground">{line}</p>
            </div>
        </header>
    );
}
