// What Work does with a `reset` (@/sdk/live): every read its views make is keyed under one of these, and each one
// mounted is read again (once per key, however many views show it). The channels layer reads its own again on its
// own timer and on focus.
import { useWorkFrames } from '@/sdk/live';
import { invalidateV1 } from '@/sdk/useV1';

export const WORK_READS = ['work:', 'resources:'] as const;

export function useReadsAgainOnReset(): void {
    useWorkFrames('reset', () => WORK_READS.forEach((prefix) => invalidateV1(prefix)));
}
