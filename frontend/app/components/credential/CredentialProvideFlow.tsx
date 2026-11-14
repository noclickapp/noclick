// The reusable core of the public credential-provide experience: fetch a
// credential request by token and connect it through the same flow the app's
// dialog uses (ConnectApp), each way in drawn by the
// method-kind registry (CredentialMethodConnect — API keys, redirect OAuth,
// agent sign-ins, WhatsApp QR, and any future kind); an AI account connects
// through Connections' own flow (AiConnect) over the link's calls. Extracted from
// credential.provide.$token so OTHER anonymous surfaces (the builder input
// bridge) embed the exact same logic and UX instead of re-implementing
// per-node credential UIs (2026-07-19: the bridge's hand-rolled connect
// button silently did nothing for WhatsApp). The coordinator's connect card
// reads the same request (useCredentialRequest) and draws its own chrome
// around the same CredentialMethodConnect.
import { useEffect, useMemo, useState } from 'react';
import type { CredentialTestConnectionResponse } from '~/types/socket-events.generated';
import { Loader2, Shield, Clock, X } from 'lucide-react';
import { cn } from '~/lib/utils';
import { getProviderConfig, getProviderConfigByCredentialType, oauthNeedsInAppSelection } from '~/utils/oauthProviders';
import { getServiceForCredentialType } from '~/utils/credentialTypes';
import { credentialAppName } from '~/utils/credentialIcons';
import { kindFromBackendMethod } from '~/lib/credentialMethodKind';
import { AGENT_SIGN_IN_NAMES, agentCompanyOf, agentCredentialProvider, signInForKey } from '~/lib/agentCredentialModel';
import { getProviderMetadata, type ModelProvider } from '~/types/provider';
import { AiConnect, companyMethods, type AiConnectVia } from '~/components/shell/connections/AiConnect';
import { aiCompanies } from '~/components/shell/connections/aiAccounts';
import { ConnectApp } from './connect/ConnectApp';
import { wayInRank } from './credentialMethods';
import {
  CredentialMethodConnect,
  provideKey,
  type ProvideCredentialMethod,
} from './CredentialMethodConnect';
import { provideLinkTransport } from './provideLinkTransport';
import { fixWordCasing, humanizeCredentialLabel } from '~/utils/credentialLabels';
import type { CredentialField } from './CredentialFieldInput';

export interface ProvideRequestDetails {
  credential_type: string;
  requester_name: string;
  /** Null for a phone-only requester (WhatsApp signup). */
  requester_email: string | null;
  message?: string;
  is_oauth: boolean;
  oauth_provider?: string;
  oauth_scopes?: string[];
  oauth_user_scopes?: string[];
  supports_custom_client?: boolean;
  requires_custom_client?: boolean;
  /** The requester brings its own OAuth app for this provider. */
  oauth_app?: boolean;
  requires_pkce: boolean;
  credential_fields: CredentialField[];
  /** Where the values come from, in steps (the schema's x-credential-instructions). */
  instructions?: string | null;
  available_methods: ProvideCredentialMethod[];
  status: string;
  expires_at: string;
  /** Where the requester asked the person to be sent once provided. */
  redirect_url?: string | null;
  /** The harness the asking agent runs on when it takes no plan: why the link offers an AI key without its sign-in. */
  sign_in_withheld?: string | null;
}

/** Convert credential_type to human-readable label */
export function formatCredentialType(type: string): string {
  return type
    .replace(/_oauth$/, '')
    .replace(/_pat$/, ' PAT')
    .replace(/_api_key$/, ' API Key')
    .replace(/_bot_token$/, ' Bot Token')
    .replace(/_api_token$/, ' API Token')
    .replace(/_bearer_token$/, ' Bearer Token')
    .replace(/_integration_token$/, ' Integration Token')
    .replace(/_access_token$/, ' Access Token')
    .replace(/_connection_string$/, ' Connection String')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
    // "Whatsapp Qr" → "WhatsApp QR": Title Case can't know acronyms/brands.
    .split(' ').map(w => fixWordCasing(w)).join(' ');
}

/** Why a request can't be provided (the provide page words each for a stranger, the chat's card for its owner):
 *  ended (`fulfilled`, `cancelled`, `expired`, as the backend types its 410), gone (`not_found`: never existed, or
 *  replaced by a newer request), out of tries, or unreadable. */
export type ProvideRequestProblem = 'fulfilled' | 'cancelled' | 'expired' | 'not_found' | 'too_many' | 'failed' | 'unreachable';

const ENDED: ProvideRequestProblem[] = ['fulfilled', 'cancelled', 'expired'];

export type ProvideRequestState =
  | { status: 'loading' }
  | { status: 'ready'; details: ProvideRequestDetails; methods: ProvideCredentialMethod[] }
  /** `credentialId`: what a fulfilled request made; `note`: why one ended unfulfilled, in words for its page (a scan
   *  of a number another agent keeps). */
  | { status: 'unavailable'; problem: ProvideRequestProblem; credentialId?: string; note?: string };

/** A credential request by its token, read once: its details and the methods it can be provided with (the
 *  backend's list, or a single method built from the details for a pre-methods request). `held` is a request the
 *  page already has (a demo's), read from nothing. */
export function useCredentialRequest(token: string, apiBase: string, held?: ProvideRequestDetails): ProvideRequestState {
  const [state, setState] = useState<ProvideRequestState>(
    held ? { status: 'ready', details: held, methods: methodsOf(held) } : { status: 'loading' },
  );

  useEffect(() => {
    if (held) return;
    let mounted = true;
    const fail = (problem: ProvideRequestProblem, credentialId?: string, note?: string) =>
      mounted && setState({ status: 'unavailable', problem, credentialId, note });
    setState((prev) => (prev.status === 'loading' ? prev : { status: 'loading' }));
    (async () => {
      try {
        const res = await fetch(`${apiBase}/api/credential-request/${token}`);
        if (!mounted) return;
        if (res.status === 410) {
          const detail = (await res.json().catch(() => ({})))?.detail;
          const ended = ENDED.find((p) => p === detail?.status) ?? 'expired';
          const str = (value: unknown) => (typeof value === 'string' ? value : undefined);
          return fail(ended, str(detail?.credential_id), str(detail?.note));
        }
        if (res.status === 429) return fail('too_many');
        if (res.status === 404) return fail('not_found');
        if (!res.ok) return fail('failed');
        const details: ProvideRequestDetails = await res.json();
        if (mounted) setState({ status: 'ready', details, methods: methodsOf(details) });
      } catch {
        fail('unreachable');
      }
    })();
    return () => { mounted = false; };
  }, [token, apiBase, held]);

  return state;
}

function methodsOf(details: ProvideRequestDetails): ProvideCredentialMethod[] {
  if (details.available_methods.length > 0) {
    return details.available_methods.map(m => ({
      ...m,
      label: humanizeCredentialLabel(m.label),
    }));
  }
  return [{
    credential_type: details.credential_type,
    label: formatCredentialType(details.credential_type),
    is_oauth: details.is_oauth,
    oauth_provider: details.oauth_provider,
    oauth_scopes: details.oauth_scopes,
    oauth_user_scopes: details.oauth_user_scopes,
    supports_custom_client: details.supports_custom_client,
    requires_custom_client: details.requires_custom_client,
    oauth_app: details.oauth_app,
    credential_fields: details.credential_fields,
    instructions: details.instructions,
  }];
}

const PROBLEMS: Record<ProvideRequestProblem, string> = {
  fulfilled: 'This credential request has already been fulfilled.',
  cancelled: 'This credential request was cancelled.',
  expired: 'This credential request has expired.',
  too_many: 'Too many attempts. Please contact the requester for a new link.',
  not_found: 'Credential request not found.',
  failed: 'Something went wrong loading this request. Please try again in a moment.',
  unreachable: 'Failed to load credential request details.',
};

/** A sign-in only the app's own connect form can run: one that picks an account or project after the popup, or one
 *  the request has no sign-in for (the provide page refuses the first and draws nothing for the second). */
export function signsInOnlyInApp(method: ProvideCredentialMethod): boolean {
  return kindFromBackendMethod(method) === 'oauth' && (!method.oauth_provider || oauthNeedsInAppSelection(method.oauth_provider));
}

/** The app a request is for, as Connections names it: an AI account's company ("Anthropic"), else the app as the
 *  catalog names it ("Notion"), else its sign-in's provider, else its type. */
export function appNameForCredentialType(credentialType: string): string {
  return (
    agentCompanyOf(credentialType)?.title ??
    getServiceForCredentialType(credentialType)?.label ??
    credentialAppName(credentialType) ??
    getProviderConfigByCredentialType(credentialType)?.name ??
    formatCredentialType(credentialType)
  );
}

/** Of a company's ways in (Connections' own, in its order and words), those a link offers: each the request lists, a
 *  key under the type the request names when it takes the same values. */
function offeredWays(ways: ProvideCredentialMethod[], offered: ProvideCredentialMethod[]): ProvideCredentialMethod[] {
  const values = (method: ProvideCredentialMethod) => method.credential_fields.map((f) => f.name).join('+');
  const isKey = (method: ProvideCredentialMethod) => kindFromBackendMethod(method) === 'api_key';
  return ways.flatMap((way) => {
    const match = offered.find((o) => o.credential_type === way.credential_type) ?? (isKey(way) ? offered.find((o) => isKey(o) && values(o) === values(way)) : undefined);
    return match ? [{ ...way, credential_type: match.credential_type }] : [];
  });
}

/** An AI account's ways in on a link: its company's, as Connections offers them, that the link lists. The sign-ins it
 *  lists stand in for the instance's, since the backend offers only those it can finish. */
function linkAiWays(credentialType: string, offered: ProvideCredentialMethod[]): ProvideCredentialMethod[] {
  if (!agentCompanyOf(credentialType)) return [];
  const signIns = offered.filter((m) => kindFromBackendMethod(m) === 'agent_oauth').map((m) => [agentCredentialProvider(m.credential_type), m.credential_type]);
  const company = aiCompanies(Object.fromEntries(signIns)).find((c) => c.credentialTypes.includes(credentialType));
  return company ? offeredWays(companyMethods(company), offered) : [];
}

/** Why a link offers an AI key without its plan's sign-in: the agent asking runs where no plan does. */
function WithheldSignIn({ keyType, harness }: { keyType: string; harness: string }) {
  const plan = signInForKey(keyType);
  if (!plan || !AGENT_SIGN_IN_NAMES[plan]) return null;
  const runsOn = harness === 'llm' ? 'NoClick’s own agent' : getProviderMetadata(harness as ModelProvider)?.title ?? harness;
  return (
    <p className="mb-5 text-[13px] leading-relaxed text-muted-foreground" data-testid="sign-in-withheld">
      Sign in with {AGENT_SIGN_IN_NAMES[plan].signInWith} isn’t offered here: the agent this is for runs on {runsOn}, which takes an API key.
    </p>
  );
}

/** Only what's typed in is sent: a sign-in sends nothing, and says nothing of it. */
function EncryptedNote() {
  return (
    <p className="mt-2 flex items-center gap-2 text-[12.5px] leading-relaxed text-muted-foreground">
      <Shield className="h-3.5 w-3.5 shrink-0" />
      It’s encrypted as soon as you send it.
    </p>
  );
}

const NO_CREDENTIALS: Record<string, string> = {};
const attachNowhere = () => {};

export function CredentialProvideFlow({
  token,
  apiBase,
  held,
  onProvided,
  onDetails,
  compact = false,
}: {
  token: string;
  apiBase: string;
  /** The request when the page already holds it (a demo's), so nothing is fetched. */
  held?: ProvideRequestDetails;
  /** Fires once the credential lands — the parent owns the success state.
      Manual credentials carry what the connect-time probe proved. */
  onProvided: (verification?: CredentialTestConnectionResponse | null) => void;
  /** Fires when request details load, for parents that render their own header. */
  onDetails?: (details: ProvideRequestDetails) => void;
  /** Tighter paddings for embedded surfaces (the builder input bridge card). */
  compact?: boolean;
}) {
  const request = useCredentialRequest(token, apiBase, held);
  const details = request.status === 'ready' ? request.details : null;

  useEffect(() => {
    if (!details) return;
    onDetails?.(details);
    if (details.credential_type === 'phone_number' && details.status === 'fulfilled') onProvided();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [details]);

  const app = useMemo(() => (details ? appNameForCredentialType(details.credential_type) : ''), [details]);
  // An AI account connects as Connections connects it (AiConnect), over the link's own calls.
  const via = useMemo<AiConnectVia>(() => ({
    signIn: (credentialType) => provideLinkTransport(apiBase, token, credentialType),
    saveKey: async (method, values) => {
      const reply = await provideKey(apiBase, token, method.credential_type, values);
      return reply.success ? { ...reply, credential: { id: reply.credential_id ?? '', name: app, credential_type: method.credential_type } } : reply;
    },
    keyNote: <EncryptedNote />,
  }), [apiBase, token, app]);

  if (request.status === 'loading') {
    return (
      <div className={cn('flex items-center justify-center gap-2 text-[13px] text-muted-foreground', compact ? 'py-6' : 'py-12')}>
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading the request…
      </div>
    );
  }
  if (request.status === 'unavailable') {
    const Icon = ENDED.includes(request.problem) ? Clock : X;
    return (
      <div className={cn('flex items-start gap-3', compact ? 'py-2' : 'py-6')}>
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-foreground/[0.06] text-muted-foreground">
          <Icon className="h-4 w-4" />
        </span>
        <p className="pt-2 text-[13.5px] leading-relaxed text-muted-foreground">{request.note ?? PROBLEMS[request.problem]}</p>
      </div>
    );
  }
  // A shared link offers only the ways in it can finish: Instagram's Facebook sign-in, which picks the account after
  // its popup, only said it couldn't be used here (2026-11-06). With no other way in, it still says why.
  const usable = request.methods.filter((method) => !signsInOnlyInApp(method));
  // In the order Connections offers them: a sign-in first.
  const methods = [...(usable.length ? usable : request.methods)].sort((a, b) => wayInRank(a) - wayInRank(b));
  if (!methods.length) return null;

  const aiWays = linkAiWays(request.details.credential_type, methods);
  if (aiWays.length) {
    return (
      <>
        {request.details.sign_in_withheld && <WithheldSignIn keyType={request.details.credential_type} harness={request.details.sign_in_withheld} />}
        <AiConnect
          app={app}
          methods={aiWays}
          credentialIds={NO_CREDENTIALS}
          onCredentialIdsChange={attachNowhere}
          onSignedIn={async () => onProvided()}
          onKeySaved={async (_credential, verification) => onProvided(verification)}
          via={via}
        />
      </>
    );
  }

  return (
    <div className="space-y-2">
      {/* The same connect flow as the app's dialog: a switch between the ways in, a key as get-it-then-paste-it
          steps. No asking someone else: whoever opened this link is the someone. */}
      <ConnectApp
        app={app}
        methods={methods}
        showResult={false}
        providerName={(method) => getProviderConfig(method.oauth_provider ?? undefined)?.name ?? app}
        renderMethod={(method, ctx) => (
          <>
            <CredentialMethodConnect
              method={method}
              apiBase={apiBase}
              token={token}
              serviceName={app}
              onProvided={onProvided}
              howTo={ctx.howTo}
              showSources={ctx.showSources}
              note={ctx.note}
            />
            {kindFromBackendMethod(method) === 'api_key' && <EncryptedNote />}
          </>
        )}
      />
    </div>
  );
}
