// What this NoClick instance can actually do, as reported by the backend.
//
// Several settings surfaces are dead without infrastructure a given install may
// not have — publishing apps needs the hosted subdomain worker, notification
// emails need a Resend key — and the UI has no way to know from the frontend
// alone. Offering a control that silently does nothing is worse than hiding it,
// so the backend reports capabilities and the UI follows.
//
// Deliberately capability-based rather than edition-based where config decides:
// a self-hoster who sets RESEND_API_KEY gets working notifications, and should
// see them.

import { useEffect, useState } from 'react';
import { apiBaseUrl } from '~/lib/hostedDefaults';

export interface InstanceCapabilities {
    /** Outbound email is configured (notification alerts can send). */
    email: boolean;
    /** Publishing interfaces as standalone apps is available. */
    publishing: boolean;
    /** Plans, top-ups and invoices exist on this instance. */
    billing: boolean;
    /** Agent subscription sign-ins this instance can complete: provider → credential type. */
    agentSignIns: Record<string, string>;
}

// Assume available until told otherwise: the hosted service has everything, and
// a failed probe should not strip the UI down.
const ASSUME_AVAILABLE: InstanceCapabilities = {
    email: true,
    publishing: true,
    billing: true,
    agentSignIns: {
        codex: 'agent_codex_oauth',
        claude_code: 'agent_claude_code_oauth',
        github_copilot: 'agent_github_copilot_oauth',
        xai: 'agent_xai_oauth',
    },
};

let cached: InstanceCapabilities | null = null;

export function useInstanceCapabilities(): InstanceCapabilities {
    const [caps, setCaps] = useState<InstanceCapabilities>(cached ?? ASSUME_AVAILABLE);

    useEffect(() => {
        if (cached) return;
        let cancelled = false;
        (async () => {
            try {
                const res = await fetch(`${apiBaseUrl()}/api/public/instance-status`, {
                    signal: AbortSignal.timeout(4000),
                });
                if (!res.ok) return;
                const body = await res.json();
                if (!body?.capabilities || cancelled) return;
                const resolved: InstanceCapabilities = { ...ASSUME_AVAILABLE, ...body.capabilities };
                cached = resolved;
                setCaps(resolved);
            } catch {
                // Older backend, or unreachable — keep the optimistic default.
            }
        })();
        return () => {
            cancelled = true;
        };
    }, []);

    return caps;
}
