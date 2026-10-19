// The reusable core of the public credential-provide experience: fetch a
// credential request by token and connect it through the same flow the app's
// dialog uses (ConnectApp), each way in drawn by the
// method-kind registry (CredentialMethodConnect — API keys, redirect OAuth,
// agent sign-ins, WhatsApp QR, and any future kind). Extracted from
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
import { getProviderConfig, getProviderConfigByCredentialType } from '~/utils/oauthProviders';
import { getServiceForCredentialType } from '~/utils/credentialTypes';
import { ConnectApp } from './connect/ConnectApp';
import {
  CredentialMethodConnect,
  type ProvideCredentialMethod,
} from './CredentialMethodConnect';
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
  /** `credentialId`: what a fulfilled request made. */
  | { status: 'unavailable'; problem: ProvideRequestProblem; credentialId?: string };

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
    const fail = (problem: ProvideRequestProblem, credentialId?: string) =>
      mounted && setState({ status: 'unavailable', problem, credentialId });
    setState((prev) => (prev.status === 'loading' ? prev : { status: 'loading' }));
    (async () => {
      try {
        const res = await fetch(`${apiBase}/api/credential-request/${token}`);
        if (!mounted) return;
        if (res.status === 410) {
          const detail = (await res.json().catch(() => ({})))?.detail;
          const ended = ENDED.find((p) => p === detail?.status) ?? 'expired';
          return fail(ended, typeof detail?.credential_id === 'string' ? detail.credential_id : undefined);
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

/** The app a request is for, as the catalog names it ("Notion"), else its sign-in's provider, else its type. */
export function appNameForCredentialType(credentialType: string): string {
  return getServiceForCredentialType(credentialType)?.label ?? getProviderConfigByCredentialType(credentialType)?.name ?? formatCredentialType(credentialType);
}

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
        <p className="pt-2 text-[13.5px] leading-relaxed text-muted-foreground">{PROBLEMS[request.problem]}</p>
      </div>
    );
  }
  const { methods } = request;
  if (!methods.length) return null;

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
        )}
      />
      <p className="flex items-center gap-2 text-[12.5px] leading-relaxed text-muted-foreground">
        <Shield className="h-3.5 w-3.5 shrink-0" />
        It’s encrypted as soon as you send it.
      </p>
    </div>
  );
}
