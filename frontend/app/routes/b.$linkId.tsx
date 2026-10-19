// Public builder input bridge page (/b/{linkId}): the bridge (components/bridge/BuilderBridge) over the link's own
// routes on the backend. Its loader reads the link once on the server so a chat's preview of it says what it asks
// ("Connect Google Business Profile"); only that title and description leave the loader.
import { useMemo } from 'react';
import type { LoaderFunctionArgs, MetaFunction } from 'react-router';
import { useParams } from 'react-router';
import { buildSeoMeta } from '~/lib/seo';
import { BuilderBridge, httpBridgeTransport, type BridgePayload } from '~/components/bridge/BuilderBridge';
import { bridgeAsk } from '~/components/bridge/bridgeAsk';

const API_BASE = typeof window !== 'undefined'
  ? ((window as unknown as { ENV?: { API_URL?: string } }).ENV?.API_URL || import.meta.env.VITE_API_URL || '')
  : (process.env.API_URL || '');

// A link the backend couldn't be asked about is described as plainly what it is, never as closed.
const UNREAD = { title: 'NoClick needs something from you', description: 'Open the link to see what it is.' };

// Capability URL: what it asks changes as it's answered, and must never be shared from a cache.
export function headers() {
  return { 'Cache-Control': 'no-store' };
}

export async function loader({ params }: LoaderFunctionArgs) {
  const api = process.env.VITE_API_URL || process.env.API_URL || '';
  const res = await fetch(`${api}/api/builder-bridge/${encodeURIComponent(params.linkId ?? '')}`, {
    headers: { Accept: 'application/json' },
    signal: AbortSignal.timeout(4000),
  }).catch(() => null);
  if (res?.ok) {
    const { title, description } = bridgeAsk((await res.json()) as BridgePayload);
    return { title, description };
  }
  if (res?.status === 404) {
    const { title, description } = bridgeAsk(null);
    return { title, description };
  }
  return UNREAD;
}

export const meta: MetaFunction<typeof loader> = ({ data }) =>
  buildSeoMeta({
    title: (data ?? UNREAD).title,
    description: (data ?? UNREAD).description,
    indexable: false,
  });

export default function BuilderBridgePage() {
  const { linkId } = useParams();
  const transport = useMemo(() => httpBridgeTransport(API_BASE, linkId ?? ''), [linkId]);
  return <BuilderBridge transport={transport} />;
}
