// One request/response socket event by name, resolving to its data and
// rejecting with the backend's error. Several events (builder answers,
// decisions, workspace listings) have no generated request model, so the name
// is passed through.
import { sendEventAsync } from '~/lib/socket-sender';

type Wire = Record<string, unknown>;
type Envelope = { error?: string; data?: Wire } & Wire;

export async function socketCall(event: string, payload: Wire = {}, timeoutMs = 30000): Promise<Wire> {
    const request = { event_name: event, ...payload } as unknown as Parameters<typeof sendEventAsync>[0];
    const response = (await sendEventAsync(request, undefined, timeoutMs)) as Envelope | null;
    if (response?.error) throw new Error(response.error);
    return (response?.data ?? response ?? {}) as Wire;
}
