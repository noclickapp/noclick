// Show configuration and retained real-input evidence without claiming delivery.
// The report is read only in setup, so ordinary canvas opens stay inexpensive. What it says comes from whoever
// renders the tab (the `canvas.setup` slot's report).
import { useSlot } from '@/slots';
import { SETUP } from '../slots';

export function ReadinessStatus({
    workflowId,
}: {
    workflowId: string;
}) {
    const { read, refresh } = useSlot(SETUP).useReport(workflowId);
    const report = read.status === 'ready' ? read.report : null;
    const error = read.status === 'failed' ? read.message : null;
    return (
        <div
            className="mt-5 rounded-lg border border-border bg-card p-4 text-sm"
            aria-live="polite"
        >
            <div className="flex items-center justify-between gap-3">
                <p className="m-0 font-medium text-foreground">
                    {report
                        ? report.title
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
                                <li key={i}>
                                    {issue}
                                </li>
                            ))}
                        </ul>
                    )}
                    {report.notes.map((note, i) => (
                        <p
                            key={i}
                            className="mb-0 text-muted-foreground"
                        >
                            {note}
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
