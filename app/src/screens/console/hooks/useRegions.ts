// The regions resources can run in, and which one is the account's default,
// read once per client and shared by every form and view that names a region.
import { regions, type Region } from 'noclick';
import { useConsole } from './useConsole';
import { useV1, type V1State } from '@/sdk/useV1';

export const ANYWHERE = 'Wherever NoClick has capacity';

export function useRegions(): V1State<Region[]> {
    const { client } = useConsole();
    return useV1('regions', () => regions({ client }));
}

/** `us-east` as people read it: `US East (us-east)`; null when it's unpinned. */
export function regionLabel(name: string | null | undefined, list: readonly Region[] | undefined): string {
    if (!name) return ANYWHERE;
    const region = list?.find((r) => r.name === name);
    return region ? `${region.label} (${region.name})` : name;
}
