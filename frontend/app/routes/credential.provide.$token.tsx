// Public credential-provision page (/credential/provide/{token}): the
// recipient of a credential request connects an account without a NoClick
// login. Chrome mirrors the builder input bridge (/b) — micro-label header,
// tokenized card, PoweredByBadge, theme toggle — and the actual fetch →
// method sections → connect flow is the shared CredentialProvideFlow.
import { type LoaderFunctionArgs, type MetaFunction } from 'react-router';
import { json, type JsonPayloadOf } from '~/lib/routerResponse';
import { useLoaderData } from 'react-router';
import { useMemo, useState } from 'react';
import { CheckCircle2, KeyRound } from 'lucide-react';
import { getProviderConfigByCredentialType } from '~/utils/oauthProviders';
import { getCredentialIcon } from '~/utils/credentialIcons';
import { getAllSerializedNodeMeta } from '~/lib/nodeCatalog.server';
import { setNodeIconData } from '~/lib/nodeIconRegistry';
import { BrandIcon } from '~/components/shared/BrandIcon';
import { PoweredByBadge } from '~/components/agent-share/PoweredByBadge';
import { PublicThemeToggle } from '~/components/shared/PublicThemeToggle';
import {
  CredentialProvideFlow,
  formatCredentialType,
  type ProvideRequestDetails,
} from '~/components/credential/CredentialProvideFlow';
import { buildSeoMeta } from '~/lib/seo';

export const meta: MetaFunction = () =>
  buildSeoMeta({
    title: 'Provide Credentials - NoClick',
    description: 'Securely share credentials with a NoClick workflow.',
    indexable: false,
  });

const API_BASE = typeof window !== 'undefined'
  ? ((window as unknown as { ENV?: { API_URL?: string } }).ENV?.API_URL || import.meta.env.VITE_API_URL || '')
  : (process.env.API_URL || '');

export async function loader({ params }: LoaderFunctionArgs) {
  const { token } = params;
  if (!token) {
    throw new Response('Missing token', { status: 400 });
  }
  // Serialize node-icon metadata so the client can resolve node-backed brand
  // icons (Apollo, Slack, …) via the same resolver Settings uses, without
  // pulling in the heavy node registry. Static + identical for every user.
  return json({ token, nodeIconData: getAllSerializedNodeMeta() });
}

export default function ProvideCredentialPage() {
  const { token, nodeIconData } = useLoaderData<JsonPayloadOf<typeof loader>>();
  // Populate the node-icon singleton before the credential icon resolves, so
  // node-backed brand icons (Apollo, Slack, …) render. Idempotent per render.
  setNodeIconData(nodeIconData);

  const [details, setDetails] = useState<ProvideRequestDetails | null>(null);
  const [provided, setProvided] = useState(false);

  const credentialIcon = useMemo(
    () => (details ? getCredentialIcon(details.credential_type) : null),
    [details],
  );
  const serviceName = useMemo(
    () => (details ? getProviderConfigByCredentialType(details.credential_type)?.name : undefined),
    [details],
  );
  const title = details
    ? `Connect ${serviceName || formatCredentialType(details.credential_type)}`
    : 'Credential request';

  return (
    <div className="min-h-dvh bg-background text-foreground flex flex-col items-center px-4 py-12">
      <PublicThemeToggle />
      <div className="w-full max-w-md flex flex-col">
        {/* Page header — the shared public-page idiom (matches /b). */}
        <div className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground dark:text-zinc-500">
          Credential request
        </div>
        <div className="mt-1.5 flex items-center gap-2.5">
          {credentialIcon?.hasServiceIcon ? (
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-foreground/[0.05]">
              <BrandIcon Icon={credentialIcon.Icon} iconColor={credentialIcon.iconColor || 'text-foreground'} className="w-4 h-4" />
            </span>
          ) : (
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-foreground/[0.05]">
              <KeyRound className="w-4 h-4 text-muted-foreground" />
            </span>
          )}
          <h1 className="text-lg font-semibold tracking-tight truncate">{title}</h1>
        </div>
        <p className="mt-1 text-[13px] leading-relaxed text-muted-foreground dark:text-zinc-500">
          {details
            ? `${details.requester_name} (${details.requester_email}) is asking you to securely connect an account for their NoClick workflow. No account needed.`
            : 'Someone is asking you to securely connect an account for their NoClick workflow. No account needed.'}
        </p>

        {/* Card — message + the shared connect flow. */}
        <div className="mt-6 rounded-2xl border border-border bg-card overflow-hidden" data-testid="provide-card">
          {provided ? (
            <div className="px-6 py-10 text-center" data-testid="provide-success">
              <CheckCircle2 className="mx-auto h-7 w-7 text-emerald-500" />
              <div className="mt-3 text-sm font-semibold">Credential provided</div>
              <p className="mt-1 text-[13px] text-muted-foreground dark:text-zinc-500">
                {details?.requester_name} has been notified and can now use this
                credential. You can safely close this page.
              </p>
            </div>
          ) : (
            <div className="px-5 py-5">
              {details?.message && (
                <div className="mb-4 border-l-2 border-foreground/20 pl-3 text-sm leading-relaxed text-foreground/90 whitespace-pre-wrap break-words">
                  {details.message}
                </div>
              )}
              <CredentialProvideFlow
                token={token}
                apiBase={API_BASE}
                compact
                onDetails={setDetails}
                onProvided={() => setProvided(true)}
              />
            </div>
          )}
        </div>

        <div className="mt-6 flex justify-center">
          <PoweredByBadge />
        </div>
      </div>
    </div>
  );
}
