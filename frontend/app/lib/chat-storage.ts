// Shared sessionStorage helpers used by the chat hooks.
//
// Centralized here so private-browsing failures, SSR, and disabled storage
// all degrade through the same try/catch path — the hooks remain functional
// (without persistence) instead of crashing.

function isAvailable(): boolean {
    return typeof window !== 'undefined' && typeof window.sessionStorage !== 'undefined';
}

export function readJson<T>(key: string, fallback: T): T {
    if (!isAvailable()) return fallback;
    try {
        const raw = window.sessionStorage.getItem(key);
        if (!raw) return fallback;
        return JSON.parse(raw) as T;
    } catch {
        return fallback;
    }
}

export function writeJson<T>(key: string, value: T): void {
    if (!isAvailable()) return;
    try {
        window.sessionStorage.setItem(key, JSON.stringify(value));
    } catch {
        // Quota exceeded, private-browsing, or disabled — degrade silently.
    }
}

export function readString(key: string): string | null {
    if (!isAvailable()) return null;
    try {
        return window.sessionStorage.getItem(key);
    } catch {
        return null;
    }
}

export function writeString(key: string, value: string): void {
    if (!isAvailable()) return;
    try {
        window.sessionStorage.setItem(key, value);
    } catch {
        // Same degrade semantics.
    }
}

/** Crypto-quality random id with a fallback for older browsers. */
export function freshConversationId(): string {
    return globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}
