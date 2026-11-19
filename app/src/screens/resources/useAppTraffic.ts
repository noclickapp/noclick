// An app's traffic over a period, and every app's week at once, their hours and days starting where the viewer is.
// Read again with everything else under `resources:`.
import { useMemo } from 'react';
import { useConsole } from '@/screens/console/hooks/useConsole';
import { useV1, type V1State } from '@/sdk/useV1';
import { ALL_USERS, Project, type AnalyticsPeriod, type AnalyticsSummary, type ProjectAnalytics } from 'noclick';
import { browserZone } from './traffic';

export function useAppTraffic(project: Project | undefined, period: AnalyticsPeriod): V1State<ProjectAnalytics> {
    const tz = useMemo(browserZone, []);
    // Nothing serves an app never deployed: no read.
    const key = project?.production ? `resources:projects/${project.id}/analytics?period=${period}&tz=${tz}` : null;
    return useV1(key, () => project!.analytics({ period, tz }));
}

/** Every app's requests this week, its users' as well as the account's own, one read for every row (none until `enabled`). */
export function useAppsWeek(enabled: boolean): V1State<AnalyticsSummary> {
    const { client } = useConsole();
    const tz = useMemo(browserZone, []);
    return useV1(enabled ? `resources:projects/analytics/summary?period=7d&tz=${tz}` : null, () =>
        Project.analyticsSummary({ client, period: '7d', tz, userFilter: ALL_USERS })
    );
}
