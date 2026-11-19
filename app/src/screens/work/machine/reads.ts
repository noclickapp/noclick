// The account's machines and what a new one can be, read once for Work's Runs in and the machine-buying dialog that
// opens from it (and, later, Resources' Machines). Sizes are read with what's no buy too, so the picker can grey a
// sold-out size and list the regions where one is sold out.
import { Machine } from 'noclick';
import { invalidateV1 } from '@/sdk/useV1';
import { useWorkV1 } from '../agents/reads';

/** Where agents run now (`/v1/compute`), and your own computers, as Resources' Machines and a space's tab read them. */
export const COMPUTE_KEY = 'resources:compute';
export const OWN_KEY = 'resources:machines/own';
/** Every machine as `GET /v1/machines` reads it, for Resources' rows (who's on each, its size, how long it's been up). */
export const MACHINE_VIEWS_KEY = 'resources:machines/views';
/** Where the account's company check for machines stands (`GET /v1/machines/vetting`). */
export const VETTING_KEY = 'work:machine-vetting';
/** One machine as its own page reads it. */
export const machineKey = (id: string) => `work:machine:${id}`;

export const MACHINES_KEY = 'work:machines';
export const useMachines = () => useWorkV1(MACHINES_KEY, (client) => Machine.list({ client }));

export const SIZES_KEY = 'work:machine-sizes';
/** Every size a host here sells, each with whether it can be bought now and what beats it (`offers.ts` reads it). */
export const useMachineSizes = () => useWorkV1(SIZES_KEY, (client) => Machine.sizes({ client, includeDominated: true }));

/** After a change to machine `id`: its page, Work's list of machines and Resources' rows read it again. */
export function rereadMachine(id: string) {
    invalidateV1(machineKey(id));
    invalidateV1(MACHINES_KEY);
    invalidateV1(COMPUTE_KEY);
    invalidateV1(OWN_KEY);
    invalidateV1(MACHINE_VIEWS_KEY);
}
