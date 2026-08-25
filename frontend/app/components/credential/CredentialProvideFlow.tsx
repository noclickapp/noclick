// The reusable core of the public credential-provide experience: fetch a
// credential request by token, pick an auth method, and connect via the
// method-kind registry (CredentialMethodConnect — API keys, redirect OAuth,
// agent sign-ins, WhatsApp QR, and any future kind). Extracted from
// credential.provide.$token so OTHER anonymous surfaces (the builder input
// bridge) embed the exact same logic and UX instead of re-implementing
// per-node credential UIs (2026-07-19: the bridge's hand-rolled connect
// button silently did nothing for WhatsApp).
import { useEffect, useMemo, useState, type ComponentType } from 'react';
import { Loader2, Shield, ExternalLink, Clock, X } from 'lucide-react';
import { cn } from '~/lib/utils';
import { getProviderConfigByCredentialType } from '~/utils/oauthProviders';
import { getCredentialIcon } from '~/utils/credentialIcons';
import {
  CredentialMethodConnect,
  type ProvideCredentialMethod,
} from './CredentialMethodConnect';
import { kindFromBackendMethod } from '~/lib/credentialMethodKind';
import { fixWordCasing, humanizeCredentialLabel } from '~/utils/credentialLabels';
import { CredentialCreateEntryButton } from './CredentialCreateEntryButton';
import type { CredentialField } from './CredentialFieldInput';

export interface ProvideRequestDetails {
  credential_type: string;
  requester_name: string;
  requester_email: string;
  message?: string;
  is_oauth: boolean;
  oauth_provider?: string;
  oauth_scopes?: string[];
  oauth_user_scopes?: string[];
  supports_custom_client?: boolean;
  requires_custom_client?: boolean;
  requires_pkce: boolean;
  credential_fields: CredentialField[];
  available_methods: ProvideCredentialMethod[];
  status: string;
  expires_at: string;
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

export function CredentialProvideFlow({
  token,
  apiBase,
  onProvided,
  onDetails,
  compact = false,
}: {
  token: string;
  apiBase: string;
  /** Fires once the credential lands — the parent owns the success state. */
  onProvided: () => void;
  /** Fires when request details load, for parents that render their own header. */
  onDetails?: (details: ProvideRequestDetails) => void;
  /** Tighter paddings for embedded surfaces (the builder input bridge card). */
  compact?: boolean;
}) {
  const [status, setStatus] = useState<'loading' | 'ready' | 'error' | 'expired'>('loading');
  const [details, setDetails] = useState<ProvideRequestDetails | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    const fetchDetails = async () => {
      try {
        const res = await fetch(`${apiBase}/api/credential-request/${token}`);
        if (!mounted) return;
        if (res.status === 410) {
          setStatus('expired');
          setErrorMessage('This credential request has expired or already been fulfilled.');
          return;
        }
        if (res.status === 429) {
          setStatus('error');
          setErrorMessage('Too many attempts. Please contact the requester for a new link.');
          return;
        }
        if (!res.ok) {
          setStatus('error');
          setErrorMessage('Credential request not found.');
          return;
        }
        const data: ProvideRequestDetails = await res.json();
        setDetails(data);
        setStatus('ready');
        onDetails?.(data);
      } catch {
        if (mounted) {
          setStatus('error');
          setErrorMessage('Failed to load credential request details.');
        }
      }
    };
    void fetchDetails();
    return () => { mounted = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, apiBase]);

  // Effective methods list — backend-provided, or a single method built from
  // the top-level details for pre-methods requests.
  const methods: ProvideCredentialMethod[] = useMemo(() => {
    if (!details) return [];
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
      credential_fields: details.credential_fields,
    }];
  }, [details]);

  const credentialIcon = useMemo(
    () => (details ? getCredentialIcon(details.credential_type) : null),
    [details],
  );
  const ServiceIcon: ComponentType<{ className?: string }> | null =
    credentialIcon?.hasServiceIcon ? credentialIcon.Icon : null;
  const serviceName = useMemo(
    () => (details ? getProviderConfigByCredentialType(details.credential_type)?.name : undefined),
    [details],
  );

  if (status === 'loading') {
    return (
      <div className={cn('text-center', compact ? 'py-6' : 'p-12')}>
        <Loader2 className={'w-6 h-6 text-muted-foreground animate-spin mx-auto mb-3'} />
        <div className={'text-sm text-muted-foreground'}>Loading request details...</div>
      </div>
    );
  }
  if (status === 'expired' || status === 'error') {
    const Icon = status === 'expired' ? Clock : X;
    const tone = status === 'expired' ? 'text-amber-400 bg-amber-500/15' : 'text-red-400 bg-red-500/15';
    return (
      <div className={cn('text-center', compact ? 'py-6' : 'p-12')}>
        <div className={cn('w-10 h-10 rounded-xl flex items-center justify-center mx-auto mb-3', tone.split(' ')[1])}>
          <Icon className={cn('w-5 h-5', tone.split(' ')[0])} />
        </div>
        <div className={'text-sm text-muted-foreground'}>{errorMessage}</div>
      </div>
    );
  }
  if (!details || !methods.length) return null;

  return (
    <div className={cn('space-y-5', compact && 'space-y-4')}>
      {/* Every auth method as its own section — heading, schema description,
          credential link, then the method's connect affordance. Mirrors
          NodeCredentials' REQUIRED CREDENTIALS layout (stacked sections, not
          a picker); api_key methods collapse behind the app's "+ Create new"
          entry point. */}
      {methods.map((method) => (
        <MethodSection
          key={method.credential_type}
          method={method}
          apiBase={apiBase}
          token={token}
          serviceName={serviceName}
          ServiceIcon={ServiceIcon}
          onProvided={onProvided}
          showHeading={methods.length > 1}
        />
      ))}

      {/* Security note */}
      <div className="flex items-center gap-2 pt-1">
        <Shield className="w-3.5 h-3.5 text-muted-foreground/60 dark:text-zinc-600 flex-shrink-0" />
        <p className="text-[11px] leading-relaxed text-muted-foreground/60 dark:text-zinc-600">
          Your credential is encrypted end-to-end.
        </p>
      </div>
    </div>
  );
}


/** One auth method as a NodeCredentials-style section: label heading, schema
 *  description, "Get your credentials here" link, then the method's own
 *  affordance — OAuth/QR/agent connect directly; api_key collapses behind the
 *  app's "+ Create new" entry point. */
function MethodSection({
  method,
  apiBase,
  token,
  serviceName,
  ServiceIcon,
  onProvided,
  showHeading,
}: {
  method: ProvideCredentialMethod;
  apiBase: string;
  token: string;
  serviceName?: string;
  ServiceIcon: ComponentType<{ className?: string }> | null;
  onProvided: () => void;
  showHeading: boolean;
}) {
  const kind = kindFromBackendMethod(method);
  const [creating, setCreating] = useState(kind !== 'api_key');
  return (
    <div className="space-y-2 max-w-md">
      {showHeading && (
        <div>
          <div className="text-sm font-semibold text-foreground">{method.label}</div>
          {method.description && (
            <p className="text-xs text-muted-foreground mt-0.5 leading-relaxed">{method.description}</p>
          )}
        </div>
      )}
      {method.credential_url && (
        <a
          href={method.credential_url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-xs text-blue-600 dark:text-blue-400 hover:underline underline-offset-2"
        >
          Get your credentials here
          <ExternalLink className="w-3 h-3" />
        </a>
      )}
      {kind === 'api_key' && !creating ? (
        <CredentialCreateEntryButton label="Create new" onClick={() => setCreating(true)} />
      ) : (
        <CredentialMethodConnect
          method={method}
          apiBase={apiBase}
          token={token}
          serviceName={serviceName}
          ServiceIcon={ServiceIcon}
          onProvided={onProvided}
          // api_key panels collapse back to "+ Create new" — the X/Cancel the
          // real panel carries. Non-panel kinds (OAuth/QR/agent) have no
          // collapse concept.
          onCancel={kind === 'api_key' ? () => setCreating(false) : undefined}
        />
      )}
    </div>
  );
}
