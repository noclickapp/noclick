/** Operator diagnostics are available in development without a hosted flag service. */
export function useDebugToolsEnabled(): boolean {
    return import.meta.env.DEV;
}
