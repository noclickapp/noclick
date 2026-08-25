interface InitOptions {
    userId?: string | null;
    clientVersion?: string | null;
    endpoint?: string;
}

export function track(_name: string, _attrs: Record<string, unknown> = {}): void {}

export async function time<T>(
    _name: string,
    _attrs: Record<string, unknown>,
    fn: () => Promise<T>
): Promise<T> {
    return fn();
}

export function initTelemetry(_options: InitOptions = {}): void {}
export function flushTelemetryNow(_reason: 'reconnect' = 'reconnect'): void {}
export function __resetTelemetryForTests(): void {}
