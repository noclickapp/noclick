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
  return <ProvideCredentialView token={token} apiBase={API_BASE} />;
}
