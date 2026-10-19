// Public credential-provision page (/credential/provide/{token}): the
// recipient of a credential request connects an account without a NoClick
// login. Chrome mirrors the builder input bridge (/b) — micro-label header,
// tokenized card, PoweredByBadge, theme toggle — and the actual fetch →
// method sections → connect flow is the shared CredentialProvideFlow.
import { type LoaderFunctionArgs, type MetaFunction } from 'react-router';
import { json, type JsonPayloadOf } from '~/lib/routerResponse';
import { useLoaderData } from 'react-router';
import { useCallback, useMemo, useState } from 'react';
import { CheckCircle2, KeyRound } from 'lucide-react';
import { getCredentialIcon } from '~/utils/credentialIcons';
import { getAllSerializedNodeMeta } from '~/lib/nodeCatalog.server';
import { setNodeIconData } from '~/lib/nodeIconRegistry';
import { BrandIcon } from '~/components/shared/BrandIcon';
import { PoweredByBadge } from '~/components/agent-share/PoweredByBadge';
import { PublicThemeToggle } from '~/components/shared/PublicThemeToggle';
import { ConnectionVerdict } from '~/components/credential/ConnectionVerdict';
import type { CredentialTestConnectionResponse } from '~/types/socket-events.generated';
import {
  appNameForCredentialType,
  CredentialProvideFlow,
  type ProvideRequestDetails,
} from '~/components/credential/CredentialProvideFlow';
import { DIALOG_MARK } from '~/components/shell/ShellDialog';
import { connectDialogHeader } from '~/components/credential/connect/connectHeader';
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

/** The requester's return address with the result appended, from the backend
 *  (it validates the address and reads the stored credential id). */
async function fetchProvideReturnUrl(apiBase: string, token: string): Promise<string> {
  const res = await fetch(`${apiBase}/api/credential-request/${token}/return`);
  const body = await res.json().catch(() => ({}));
  if (!res.ok || typeof body.redirect_url !== 'string') {
    throw new Error(body.detail || 'Could not find where to return you.');
  }
  return body.redirect_url;
}

export default function ProvideCredentialPage() {
  const { token, nodeIconData } = useLoaderData<JsonPayloadOf<typeof loader>>();
  // Populate the node-icon singleton before the credential icon resolves, so
  // node-backed brand icons (Apollo, Slack, …) render. Idempotent per render.
  setNodeIconData(nodeIconData);

  const [details, setDetails] = useState<ProvideRequestDetails | null>(null);
  const [provided, setProvided] = useState(false);
  // What landed: undefined for a sign-in (or a scan, a bought number), whose completing is the proof; null for a key
  // nothing could vouch for; else what the connect-time check proved.
  const [verification, setVerification] = useState<CredentialTestConnectionResponse | null | undefined>(undefined);
  const [returnError, setReturnError] = useState<string | null>(null);
  const redirects = Boolean(details?.redirect_url);

  const onProvided = useCallback((v?: CredentialTestConnectionResponse | null) => {
    setVerification(v);
    setProvided(true);
    if (!redirects) return;
    fetchProvideReturnUrl(API_BASE, token)
      .then((url) => window.location.assign(url))
      .catch((e: Error) => setReturnError(e.message));
  }, [redirects, token]);

  const credentialIcon = useMemo(
    () => (details ? getCredentialIcon(details.credential_type) : null),
    [details],
  );
  const app = useMemo(() => (details ? appNameForCredentialType(details.credential_type) : null), [details]);
  const doneTitle = connectDialogHeader(app ?? 'It', 'done', { kind: verification === undefined ? 'oauth' : 'api_key', verification }).title;
  const requester = details ? `${details.requester_name}${details.requester_email ? ` (${details.requester_email})` : ''}` : 'Someone';

  // The connect dialog's composition as a page: the app's mark, the title in the brand face with one line under it,
  // what the requester wrote, then the connect flow itself, never boxed.
  return (
    <div className="min-h-dvh bg-background text-foreground flex flex-col items-center px-4 py-12 sm:py-16">
      <PublicThemeToggle />
      <div className="w-full max-w-[440px] flex flex-col">
        <span className={DIALOG_MARK}>
          {credentialIcon?.hasServiceIcon ? (
            <BrandIcon Icon={credentialIcon.Icon} iconColor={credentialIcon.iconColor || 'text-foreground'} className="h-[22px] w-[22px]" />
          ) : (
            <KeyRound className="h-5 w-5 text-muted-foreground" />
          )}
        </span>
        <h1 className="mt-5 font-brand text-[26px] font-medium leading-tight tracking-[-0.02em] [text-wrap:balance]">
          {provided ? doneTitle : app ? `Connect ${app}` : 'Connect an account'}
        </h1>
        <p
          className="mt-1.5 text-[14px] leading-relaxed text-muted-foreground [text-wrap:balance]"
          data-testid={provided ? 'provide-success-note' : undefined}
        >
          {provided
            ? redirects && !returnError
              ? 'Taking you back…'
              : `${details?.requester_name ?? 'They'} can use it now. You can safely close this page.`
            : `${requester} asked you to connect ${app ?? 'an account'} for their NoClick automations. You don’t need a NoClick account.`}
        </p>

        <div className="mt-7" data-testid="provide-card">
          {provided ? (
            <div data-testid="provide-success">
              {returnError && (
                <p className="mb-4 text-[13px] text-red-600 dark:text-red-400" role="alert">{returnError}</p>
              )}
              {/* What the connect-time probe proved: the provider's own data, so the person who typed the key sees it
                  worked, not just landed, and "Saved, not verified" when nothing could vouch for it. A sign-in has no
                  probe here (this page can't ask the provider as anyone); its completing is the proof. */}
              {verification !== undefined ? (
                <ConnectionVerdict verification={verification} providerLabel={app ?? 'The provider'} />
              ) : (
                <p className="flex items-center gap-2.5 text-[14.5px] font-medium">
                  <CheckCircle2 className="h-5 w-5 text-emerald-600 dark:text-emerald-400" />
                  Connected
                </p>
              )}
            </div>
          ) : (
            <>
              {details?.message && (
                <blockquote className="mb-6 whitespace-pre-wrap break-words border-l-2 border-foreground/20 pl-3 text-[14px] leading-relaxed text-foreground/90">
                  {details.message}
                </blockquote>
              )}
              <CredentialProvideFlow
                token={token}
                apiBase={API_BASE}
                compact
                onDetails={setDetails}
                onProvided={onProvided}
              />
            </>
          )}
        </div>

        <div className="mt-10 flex justify-center">
          <PoweredByBadge />
        </div>
      </div>
    </div>
  );
}
