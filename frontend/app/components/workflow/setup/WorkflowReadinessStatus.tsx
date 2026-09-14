// Show configuration and retained real-input evidence without claiming delivery.
// The report is loaded only in setup, so ordinary canvas opens stay inexpensive.
import { useCallback, useEffect, useState } from 'react';
import { sendEventAsync } from '~/lib/socket-sender';

import type { WorkflowReadinessReport } from '~/types/socket-events.generated';
type ReadinessReport = WorkflowReadinessReport;

const labels: Record<ReadinessReport['status'], string> = {
    needs_setup: 'Finish setup before activation',
    configured: 'Configuration valid — verify with a real input',
    waiting_for_input: 'Registered — waiting for a real input',
    deadline_armed: 'Deadline armed — waiting for the reporting window',
    input_observed: 'Real input observed',
    manual_only: 'No automatic input configured',
};

export function WorkflowReadinessStatus({
    workflowId,
}: {
    workflowId: string;
}) {
    const [report, setReport] = useState<ReadinessReport | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [revision, setRevision] = useState(0);
    const refresh = useCallback(() => setRevision((value) => value + 1), []);
    useEffect(() => {
        let cancelled = false;
        setError(null);
        setReport(null);
        void (async () => {
            try {
                const response = await sendEventAsync({
                    event_name: 'workflow:get',
                    workflow_id: workflowId,
                    include_readiness: true,
                });
                if (!response?.readiness)
                    throw new Error('Could not verify setup. Try refreshing.');
                if (!cancelled) setReport(response.readiness);
            } catch (cause) {
                if (!cancelled)
                    setError(
                        cause instanceof Error
                            ? cause.message
                            : 'Could not verify setup.'
                    );
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [workflowId, revision]);
    return (
        <div
            className="mt-5 rounded-lg border border-border bg-card p-4 text-sm"
            aria-live="polite"
        >
            <div className="flex items-center justify-between gap-3">
                <p className="m-0 font-medium text-foreground">
                    {report
                        ? labels[report.status]
                        : error
                          ? 'Setup check unavailable'
                          : 'Checking setup…'}
                </p>
                <button
                    type="button"
                    onClick={refresh}
                    className="text-xs text-muted-foreground hover:text-foreground"
                    disabled={!report && !error}
                >
                    Refresh
                </button>
            </div>
            {error && <p className="mb-0 text-muted-foreground">{error}</p>}
            {report && (
                <>
                    {report.issues.length > 0 && (
                        <ul className="mb-0 space-y-1 pl-4 text-muted-foreground">
                            {report.issues.map((issue, i) => (
                                <li key={`${issue.node_id}-${i}`}>
                                    {issue.message}
                                </li>
                            ))}
                        </ul>
                    )}
                    {report.destinations.map((destination) => (
                        <p
                            key={destination.node_id + destination.operation}
                            className="mb-0 text-muted-foreground"
                        >
                            Restricted alert destination:{' '}
                            {destination.recipients.join(', ')}
                        </p>
                    ))}
                    {report.observations.map((observation) => (
                        <p
                            key={observation.node_id}
                            className="mb-0 text-muted-foreground"
                        >
                            {observation.node_id}: input received{' '}
                            {new Date(observation.created_at).toLocaleString()}.
                            Processing: {observation.run_status}.
                        </p>
                    ))}
                    {(report.alarm_node_ids?.length ?? 0) > 0 &&
                        !report.deadline_watches?.length && (
                            <p className="mb-0 text-muted-foreground">
                                Missing-update checks have no armed reporting
                                deadline yet.
                            </p>
                        )}
                    {report.deadline_watches?.map((watch) => (
                        <p
                            key={watch.node_id + watch.watch_key}
                            className="mb-0 text-muted-foreground"
                        >
                            {watch.watch_key}: reporting deadline{' '}
                            {new Date(watch.deadline).toLocaleString()} —{' '}
                            {watch.status}.
                            {watch.last_seen_at
                                ? ` Last update: ${new Date(watch.last_seen_at).toLocaleString()}.`
                                : ' No update recorded yet.'}
                        </p>
                    ))}
                    <p className="mb-0 text-xs text-muted-foreground">
                        Test Runs are simulated. Verify the intended alert with
                        a real input; a send accepted by the provider does not
                        confirm delivery.
                    </p>
                </>
            )}
        </div>
    );
}
