// Resources' slots: the places in it a host may fill (src/slots.ts), each with what stands there otherwise.
import type { ComponentType, ReactNode } from 'react';
import { slot } from '@/slots';
import type { NumberPurchaseTransport } from '@/screens/numbers/usePhoneNumberPurchase';
import type { KindId } from './kinds';
import type { ResourceItem } from './model';
import type { PlatformResources } from './platform';
import { NoMoreKinds, StandardMarkdown, StandardNumbers } from './slotStandards';

/** Items of the kinds Resources lists, with what draws them: Work's kinds (workKinds.tsx), and what a host adds. */
export interface MoreKinds {
    items: Partial<Record<KindId, ResourceItem[]>>;
    loading: Partial<Record<KindId, boolean>>;
    errors: Partial<Record<KindId, string>>;
    /** Whether `item` is one of these: its row, its page and its removal are then drawn by the parts below. */
    owns(item: ResourceItem): boolean;
    Body?: PlatformResources['Body'];
    Actions?: PlatformResources['Actions'];
    Create?: PlatformResources['Create'];
    Empty?: PlatformResources['Empty'];
    Notice?: PlatformResources['Notice'];
    unavailable?: PlatformResources['unavailable'];
    Lead?: PlatformResources['Lead'];
    Page?: PlatformResources['Page'];
    RowMenu?: PlatformResources['RowMenu'];
    removal?: PlatformResources['removal'];
}

/** Around the page: items a host adds to the kinds Resources lists, read by the host and handed on. Nothing stands
 *  there: Resources lists what the platform API reads. */
export const MORE_KINDS = slot<ComponentType<{ children: (more: MoreKinds) => ReactNode }>>('resources.kinds', NoMoreKinds);

/** The account's numbers as Resources lists them. */
export interface NumbersRead {
    items: ResourceItem[];
    loading: boolean;
    /** Why they couldn't be read, in a sentence. */
    error?: string;
    /** What a number costs a month, in US dollars, by its id, where its item carries no price of its own. */
    monthly: ReadonlyMap<string, number>;
    /** How the page for buying one buys it. */
    transport: NumberPurchaseTransport;
    refresh(): void;
}

/** Around the page: the account's numbers, read and handed on. The standard reads the platform API's phone numbers,
 *  each with its own monthly price, and buys one through it. */
export const NUMBERS = slot<ComponentType<{ children: (numbers: NumbersRead) => ReactNode }>>('resources.numbers', StandardNumbers);

/** On a number's page, beside its facts: what can be done with it. Nothing stands there. */
export const NUMBER_ACTIONS = slot<ComponentType<{ item: ResourceItem }>>('resources.number.actions', () => null);

/** In a file's preview: a Markdown file's text, drawn. The standard draws it as a code repository's README is. */
export const FILE_MARKDOWN = slot<ComponentType<{ content: string; className?: string }>>('resources.file.markdown', StandardMarkdown);
