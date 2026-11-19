// The platform client Work's views read and write with: the page provides the
// dashboard's (useDashboardClient), tests and fixtures provide one over a fake transport.
import { createContext, useContext } from 'react';
import type { NoClick } from 'noclick';

export const WorkClientContext = createContext<NoClick | null>(null);

export function useWorkClient(): NoClick {
    const client = useContext(WorkClientContext);
    if (!client) throw new Error('Work views render inside WorkClientContext.');
    return client;
}
