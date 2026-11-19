// Resources' platform for machines alone, as the hosted provider gives it, for tests and screenshots over Work's fake
// /v1: Machines' rows (placeItem over /v1/compute, your own computers and each machine's own read), Add machine, the
// empty tab's two ways, the company check's notice, and a machine's own page.
import type { ReactNode } from 'react';
import { ALL_USERS, Machine } from 'noclick';
import { getMachineAccess } from '@/sdk/owner';
import { listCompute, listOwnComputers } from '@/screens/resources/knowledge';
import { placeItem } from '@/screens/resources/knowledgeItems';
import { KINDS } from '@/screens/resources/kinds';
import { PlatformResourcesContext, type PlatformResources } from '@/screens/resources/platform';
import { useAgents, useWorkV1 } from '../../agents/reads';
import {
    AddMachine,
    MachinesNotice,
    MachineWays,
} from '../../resources/inResources';
import { MachineResourcePage } from '../../resources/machinePage';
import { COMPUTE_KEY, MACHINE_VIEWS_KEY, OWN_KEY, VETTING_KEY } from '../reads';

export function MachinesPlatform({ children }: { children: ReactNode }) {
    const compute = useWorkV1(COMPUTE_KEY, listCompute);
    const own = useWorkV1(OWN_KEY, listOwnComputers);
    const views = useWorkV1(MACHINE_VIEWS_KEY, (client) =>
        Machine.list({ client, userFilter: ALL_USERS })
    );
    const vetting = useWorkV1(VETTING_KEY, (client) =>
        getMachineAccess(client)
    );
    const agents = useAgents().data ?? [];
    const places = [...(compute.data?.data ?? []), ...(own.data ?? [])];
    const machines = places.map((p) => {
        const v = views.data?.find((m) => m.id === p.id);
        return placeItem(p, undefined, {
            agents: agents
                .filter((a) => a.machineId === p.id)
                .map((a) => a.name),
            size: v?.size ?? null,
            startedAt: (v?.raw.started_at as string | null | undefined) ?? null,
            status: v?.raw.status as string | undefined,
            os: v?.os ?? null,
            company: vetting.data?.company_name ?? null,
        });
    });
    const value: PlatformResources = {
        items: { machines },
        loading: { machines: !compute.data || !own.data },
        errors: {},
        spentThisMonth: {},
        numberPrices: new Map(),
        numberTransport: {} as PlatformResources['numberTransport'],
        refresh: () => undefined,
        registrar: {} as PlatformResources['registrar'],
        serveApp: async () => undefined,
        mailDomains: [],
        createAddress: async () => '',
        Body: () => null,
        Create: { machines: AddMachine },
        Empty: { machines: MachineWays },
        Notice: { machines: MachinesNotice },
        Page: { machines: MachineResourcePage },
        kinds: KINDS,
        hostOwns: (item) => item.kind === 'machines',
        removal: () => null,
        trash: {},
        restore: async () => undefined,
        purge: async () => undefined,
    };
    return (
        <PlatformResourcesContext.Provider value={value}>
            {children}
        </PlatformResourcesContext.Provider>
    );
}
