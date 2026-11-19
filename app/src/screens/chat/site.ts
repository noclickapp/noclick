// NoClick's own site as the console context names it, for the chat's links to its pages (an approval's, billing). A
// piece drawn outside a console's context (a page of a host that is NoClick's site itself) links within that site, as
// `useOwnerOnly` takes such a piece to act as its owner.
import { useContext } from 'react';
import { ConsoleContext } from '@/screens/console/hooks/useConsole';

export function useSite(): string {
    return useContext(ConsoleContext)?.site ?? '';
}
