// Public credential-provision page (/credential/provide/{token}): the
// recipient of a credential request connects an account without a NoClick
// login. Chrome mirrors the builder input bridge (/b) — micro-label header,
// tokenized card, PoweredByBadge, theme toggle — and the actual fetch →
// method sections → connect flow is the shared CredentialProvideFlow, drawn by
// ProvideCredentialView.
import { type LoaderFunctionArgs, type MetaFunction } from 'react-router';
import { json, type JsonPayloadOf } from '~/lib/routerResponse';
import { useLoaderData } from 'react-router';
import { getAllSerializedNodeMeta } from '~/lib/nodeCatalog.server';
import { setNodeIconData } from '~/lib/nodeIconRegistry';
import { ProvideCredentialView } from '~/components/credential/ProvideCredentialView';
import { appNameForCredentialType } from '~/components/credential/CredentialProvideFlow';
import { buildSeoMeta } from '~/lib/seo';
import { connectPreview } from '~/lib/linkPreviews';
import { AGENT_SIGN_IN_NAMES } from '~/lib/agentCredentialModel';

export const meta: MetaFunction = ({ data }) =>
  buildSeoMeta({ ...connectPreview((data as JsonPayloadOf<typeof loader> | undefined)?.account ?? null), indexable: false });

const API_BASE = typeof window !== 'undefined'
  ? ((window as unknown as { ENV?: { API_URL?: string } }).ENV?.API_URL || import.meta.env.VITE_API_URL || '')
  : (process.env.API_URL || '');

// The account the request asks for, as a chat's preview of the link names it ("Connect your Claude account"): read
// once on the server, and only its name leaves the loader. A request that has ended, or couldn't be read, previews as
// any account; the page reads it again itself.
async function requestedAccount(token: string): Promise<string | null> {
  const api = process.env.VITE_API_URL || process.env.API_URL || '';
  const res = await fetch(`${api}/api/credential-request/${encodeURIComponent(token)}`, {
    headers: { Accept: 'application/json' },
    signal: AbortSignal.timeout(4000),
  }).catch((error: unknown) => {
    console.warn('[credential-provide] reading the request for its preview failed:', error);
    return null;
  });
  if (!res?.ok) {
    if (res && ![404, 410, 429].includes(res.status)) console.warn(`[credential-provide] the request's preview read answered ${res.status}`);
    return null;
  }
  const { credential_type: type } = (await res.json()) as { credential_type?: string };
  // A plan is an account with what it signs in with (a Claude plan is a Claude account); anything else, its app.
  return type ? (AGENT_SIGN_IN_NAMES[type]?.signInWith ?? appNameForCredentialType(type)) : null;
}

export async function loader({ params }: LoaderFunctionArgs) {
  const { token } = params;
  if (!token) {
    throw new Response('Missing token', { status: 400 });
  }
  // Serialize node-icon metadata so the client can resolve node-backed brand
  // icons (Apollo, Slack, …) via the same resolver Settings uses, without
  // pulling in the heavy node registry. Static + identical for every user.
  const nodeIconData = getAllSerializedNodeMeta();
  // The app names its account through the same catalog.
  setNodeIconData(nodeIconData);
  return json({ token, nodeIconData, account: await requestedAccount(token) });
}

export default function ProvideCredentialPage() {
  const { token, nodeIconData } = useLoaderData<JsonPayloadOf<typeof loader>>();
  // Populate the node-icon singleton before the credential icon resolves, so
  // node-backed brand icons (Apollo, Slack, …) render. Idempotent per render.
  setNodeIconData(nodeIconData);
  return <ProvideCredentialView token={token} apiBase={API_BASE} />;
}
