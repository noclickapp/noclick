// What stands in Resources' slots when no host fills them (slots.ts).
import { useMemo, type ReactNode } from 'react';
import { PhoneNumber } from 'noclick';
import { useV1 } from '@/sdk/useV1';
import { useConsole } from '@/screens/console/hooks/useConsole';
import { useConsoleNumberTransport } from '@/screens/console/pages/resources/PhoneNumbersPanel';
import { errorText } from '@/screens/console/pages/resources/shared';
import { formatNumber } from '@/screens/numbers/numberDisplay';
import { dateLabel } from '@/ui/primitives';
import { MarkdownDoc } from './CodeView';
import type { ResourceItem } from './model';
import type { MoreKinds, NumbersRead } from './slots';

const NONE: MoreKinds = { kinds: [], items: {}, loading: {}, errors: {}, owns: () => false };
/** Each number carries its own price. */
const OWN_PRICES: ReadonlyMap<string, number> = new Map();

export function NoMoreKinds({ children }: { children: (more: MoreKinds) => ReactNode }) {
    return <>{children(NONE)}</>;
}

/** A number the account holds, as the platform API lists it, with its own monthly price. */
function numberItem(number: PhoneNumber): ResourceItem {
    const added = number.createdAt?.toISOString() ?? null;
    return {
        id: number.id,
        kind: 'numbers',
        title: formatNumber(number.number),
        subtitle: number.texts ? 'Calls and texts' : 'Calls',
        updatedAt: added,
        usedBy: [],
        // A number whose price NoClick didn't record has none to show, which isn't one that costs nothing.
        ...(number.monthlyUsd === null ? {} : { price: { usd: number.monthlyUsd, per: 'month' as const } }),
        platform: { facts: [['Name', number.name ?? '—'], ['Added', added ? dateLabel(added) : '—']] },
    };
}

/** The account's numbers from the platform API, which lists every number the account holds, however it was bought. */
export function StandardNumbers({ children }: { children: (numbers: NumbersRead) => ReactNode }) {
    const { client } = useConsole();
    const read = useV1('resources:numbers', () => PhoneNumber.listPage({ client, limit: 100 }));
    const transport = useConsoleNumberTransport(client, { user: null, name: '' });
    const page = read.data?.data;
    const items = useMemo(() => (page ?? []).filter((n) => !n.released).map(numberItem), [page]);
    const numbers: NumbersRead = {
        items,
        loading: read.loading,
        error: read.error !== undefined && read.data === undefined ? errorText(read.error) : undefined,
        monthly: OWN_PRICES,
        transport,
        refresh: () => void read.refresh(),
    };
    return <>{children(numbers)}</>;
}

export function StandardMarkdown({ content, className }: { content: string; className?: string }) {
    return <MarkdownDoc source={content} className={className} />;
}
