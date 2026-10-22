// A phone-number purchase link's backend calls, as its signed-in owner: the page's loader reads the request, the
// operations route searches, quotes, confirms and re-reads it.
import { apiBaseUrl } from '~/lib/hostedDefaults';

export const PURCHASE_OPERATIONS = [
    'coverage',
    'places',
    'search',
    'quote',
    'confirm',
    'status',
    'resubmit',
    'documents',
    'document_upload',
    'document_remove',
] as const;

type PurchaseReply<T> = T & { error?: string; kind?: string };

export async function phonePurchaseBackend<T = Record<string, unknown>>(
    token: string,
    as: Record<string, string>,
    operation?: string,
    body?: unknown
): Promise<PurchaseReply<T>> {
    const res = await fetch(`${apiBaseUrl()}/api/credential-request/${encodeURIComponent(token)}/phone${operation ? `/${operation}` : ''}`, {
        method: operation ? 'POST' : 'GET',
        headers: { ...as, 'Content-Type': 'application/json' },
        ...(operation ? { body: JSON.stringify(body) } : {}),
        signal: AbortSignal.timeout(90_000),
    });
    // A gateway's error page is still an answer: say the request failed rather than throwing on its HTML.
    const text = await res.text();
    let data: Record<string, unknown>;
    try {
        data = JSON.parse(text);
    } catch {
        return { error: res.ok ? 'Could not read the reply.' : `Could not complete this request (${res.status}).` } as PurchaseReply<T>;
    }
    if (!res.ok) {
        const detail = data.detail as string | { error?: string; kind?: string } | undefined;
        const failure = typeof detail === 'string' ? { error: detail } : { error: detail?.error || 'Could not complete this request.', kind: detail?.kind };
        return failure as PurchaseReply<T>;
    }
    return data as PurchaseReply<T>;
}
