// The frame every lazy page renders in: a skeleton while its chunk loads and an
// error boundary that resets when the address changes. The console and the hubs
// (which embed pages in tabs) share it.
import { Component, Suspense, type ErrorInfo, type ReactNode } from 'react';
import { ErrorPanel } from './ErrorPanel';

class PageBoundary extends Component<{ children: ReactNode; resetKey: string }, { error: unknown }> {
    state = { error: undefined as unknown };
    static getDerivedStateFromError(error: unknown) {
        return { error };
    }
    componentDidUpdate(prev: { resetKey: string }) {
        if (prev.resetKey !== this.props.resetKey && this.state.error !== undefined) this.setState({ error: undefined });
    }
    componentDidCatch(error: unknown, info: ErrorInfo) {
        console.error('Developer console page crashed', error, info.componentStack);
    }
    render() {
        if (this.state.error !== undefined) return <ErrorPanel error={this.state.error} onRetry={() => this.setState({ error: undefined })} />;
        return this.props.children;
    }
}

function PageSkeleton() {
    return (
        <div aria-busy className="flex flex-col gap-3">
            <div className="h-6 w-40 animate-pulse rounded bg-foreground/[0.07]" />
            <div className="h-4 w-96 max-w-full animate-pulse rounded bg-foreground/[0.05]" />
            <div className="mt-4 h-64 animate-pulse rounded-xl bg-foreground/[0.04]" />
        </div>
    );
}

/** Suspense and the error boundary around one lazy page. */
export function PageFrame({ resetKey, children }: { resetKey: string; children: ReactNode }) {
    return (
        <PageBoundary resetKey={resetKey}>
            <Suspense fallback={<PageSkeleton />}>{children}</Suspense>
        </PageBoundary>
    );
}
