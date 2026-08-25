/**
 * Compatibility view for installations without a managed credit policy.
 * Usage accounting remains available on the Usage page; this hook reports
 * that the instance itself imposes no allowance or purchase boundary.
 */

export interface CreditUsage {
    used: number;
    limit: number | null;
    period: 'day' | 'month' | null;
    monthlyUsed: number | null;
    monthlyCap: number | null;
    poolUserId: string | null;
    exhausted: boolean;
    refresh: () => Promise<void>;
}

const refresh = async (): Promise<void> => {};

export function useCreditUsage(): CreditUsage {
    return {
        used: 0,
        limit: null,
        period: 'month',
        monthlyUsed: 0,
        monthlyCap: null,
        poolUserId: null,
        exhausted: false,
        refresh,
    };
}
