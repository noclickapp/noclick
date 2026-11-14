// Whether NoClick is running as an app added to the home screen rather than in a browser tab.
// An installed app keeps its own sign-in, apart from the browser's, and a link tapped in Mail opens the
// browser rather than the app, so the pages that send such links say where to come back to.
import { useEffect, useState } from 'react';

function runningInstalled(): boolean {
    if (typeof window === 'undefined') return false;
    const iosStandalone = (navigator as Navigator & { standalone?: boolean }).standalone === true;
    return iosStandalone || window.matchMedia('(display-mode: standalone)').matches;
}

export function useInstalledApp(): boolean {
    // False on the server and the first client render, so hydration matches; set once mounted.
    const [installed, setInstalled] = useState(false);
    useEffect(() => setInstalled(runningInstalled()), []);
    return installed;
}
