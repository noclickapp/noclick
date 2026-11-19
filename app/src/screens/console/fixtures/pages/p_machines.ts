// Machines: where the account's request for them stands, its machines, and what runs now (`/v1/compute`). Populated,
// it's approved with one; empty and first-run, not asked yet; asking answers it under review with what was sent.
import { FIXTURE_NOW, PAGE_ERROR, ok, pageList, type FixtureRoute } from '../core';
import type { MachineAccessStatus, MachineAccessView } from '@/sdk/owner';

const POLICY = '2026-10-08';

export function machineAccess(status: MachineAccessStatus): MachineAccessView {
    if (status === 'not_submitted') return { object: 'machine_vetting', status, policy_version: POLICY };
    return {
        object: 'machine_vetting',
        status,
        policy_version: POLICY,
        company_name: 'Acme Support Ltd',
        website: 'https://acme.test',
        country: 'GB',
        use_case: 'Claude Code agents that answer support tickets around the clock, one container per conversation.',
        submitted_at: '2026-09-24T10:12:00+00:00',
        decided_at: status === 'pending' ? null : '2026-09-25T08:40:00+00:00',
        reason: status === 'rejected' ? "We couldn't reach the company's website." : null,
    };
}

export const MACHINES = [
    {
        object: 'machine',
        id: '6f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0',
        name: 'support-box',
        kind: 'noclick',
        size: 'small',
        cpu: 2,
        memory_gb: 4,
        disk_gb: 80,
        region: 'eu',
        status: 'running',
        status_reason: null,
        monthly_usd: 31.2,
        max_monthly_usd: 40,
        network: true,
        volumes: {},
        ports: [],
        agent_count: 2,
        image: 'noclick-machine-2026.10',
        restarts: 0,
        last_restart_at: null,
        user_id: null,
        created_at: '2026-09-25T09:02:00+00:00',
    },
];

/** A machine as `/v1/compute` lists it: priced as charged, with nothing running on it yet. */
const asCompute = (m: (typeof MACHINES)[number]) => ({
    object: 'compute',
    kind: 'machine',
    id: m.id,
    name: m.name,
    status: m.status,
    user_id: m.user_id,
    region: m.region,
    cpu: m.cpu,
    memory_gb: m.memory_gb,
    started_at: m.created_at,
    usd_per_hour: Math.round((m.monthly_usd / 730) * 1e6) / 1e6,
    usd_per_month: m.monthly_usd,
    spent_usd_today: null,
    running: [],
});

export const routes: readonly FixtureRoute[] = [
    // `kind` narrows them: none of the account's machines is a computer of its own.
    { method: 'GET', path: '/v1/machines', reply: (r) => pageList(r, MACHINES.filter((m) => !r.query.get('kind') || m.kind === r.query.get('kind'))) },
    { method: 'GET', path: '/v1/compute', reply: (r) => pageList(r, MACHINES.map(asCompute)) },
    {
        method: 'GET',
        path: '/v1/machines/vetting',
        reply: (r) => (r.set === 'error' ? PAGE_ERROR : ok(machineAccess(r.set === 'populated' ? 'approved' : 'not_submitted'))),
    },
    {
        method: 'POST',
        path: '/v1/machines/vetting',
        reply: (r) => {
            const body = (r.body ?? {}) as Record<string, string>;
            return ok({
                ...machineAccess('pending'),
                company_name: body.company_name,
                website: body.website,
                country: body.country,
                use_case: body.use_case,
                submitted_at: FIXTURE_NOW,
            });
        },
    },
];
