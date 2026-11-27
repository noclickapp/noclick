// Usage: the app's own page (src/screens/usage), drawn in the console's frame, so spend reads the same wherever it's
// looked at. It reads with the console's client and hears the console's live frames; caps are set where each thing is
// (a key's on API keys, a user's on their page, an agent's on its page).
import { useMemo } from 'react';
import { UsagePage } from '@/screens/usage/UsagePage';
import { createWorkLive, WorkLiveContext } from '@/sdk/live';
import { useConsole } from '@/screens/console/hooks/useConsole';

export default function Usage() {
    const { live } = useConsole();
    // Where the host has no live frames, a source that never moves: the page reads again on focus.
    const still = useMemo(() => createWorkLive(), []);
    return (
        <WorkLiveContext.Provider value={live ?? still}>
            <UsagePage />
        </WorkLiveContext.Provider>
    );
}
