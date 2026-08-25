// Client-side validation for agent sandbox environment variables, so a bad name is
// caught while typing instead of failing the run at dispatch. Mirrors
// backend/nodes/agent/user_env.py — the backend remains the authority and
// re-validates every bundle; this is purely for feedback. Keep the two in sync.

export const AGENT_ENV_CREDENTIAL_TYPE = 'agent_env';

export interface EnvRow {
    key: string;
    value: string;
}

const VALID_KEY = /^[A-Za-z_][A-Za-z0-9_]*$/;

// NoClick reserves NC_* for runtime-managed settings.
const RESERVED_PREFIXES = ['NC_'];

// Process startup and module-loading variables are runtime-managed.
const RESERVED_RUNTIME = [
    'PATH', 'HOME', 'PWD', 'SHELL', 'USER', 'LOGNAME',
    'PYTHONPATH', 'PYTHONHOME', 'LD_PRELOAD', 'LD_LIBRARY_PATH',
];

// Provider auth belongs on the separately configured model credential.
const RESERVED_PROVIDER = [
    'OPENAI_API_KEY', 'OPENAI_BASE_URL',
    'ANTHROPIC_API_KEY', 'ANTHROPIC_BASE_URL', 'ANTHROPIC_AUTH_TOKEN',
    'CODEX_API_KEY', 'CODEX_ACCESS_TOKEN',
    'CLAUDE_CODE_OAUTH_TOKEN', 'OPENROUTER_API_KEY',
    'GEMINI_API_KEY', 'GOOGLE_API_KEY',
];

const RESERVED_NAMES = new Set([...RESERVED_RUNTIME, ...RESERVED_PROVIDER]);

export function isReservedEnvName(name: string): boolean {
    return RESERVED_NAMES.has(name) || RESERVED_PREFIXES.some(p => name.startsWith(p));
}

/** Returns an error message, or null when the name is usable. */
export function validateEnvName(name: string): string | null {
    if (!VALID_KEY.test(name)) {
        return `"${name}" must use letters, digits and underscores, and not start with a digit.`;
    }
    if (isReservedEnvName(name)) {
        return `"${name}" is reserved by the agent sandbox. Provider API keys belong on the agent's model credential.`;
    }
    return null;
}

/**
 * Extract requested variable names from a node's canvas-only `agent_env_requested`
 * value — the builder's demand-driven declaration. Entries are "NAME" strings or
 * {name, description} objects; anything malformed is skipped (read path, no throw).
 */
export function parseRequestedEnvNames(requested: unknown): string[] {
    if (!Array.isArray(requested)) return [];
    const names: string[] = [];
    for (const entry of requested) {
        if (typeof entry === 'string' && entry.trim()) names.push(entry.trim());
        else if (entry && typeof entry === 'object') {
            const n = (entry as { name?: unknown }).name;
            if (typeof n === 'string' && n.trim()) names.push(n.trim());
        }
    }
    return names;
}

/**
 * Variable names left blank. On EDIT these are destructive: `credential:update`
 * replaces the whole blob and the browser never holds the stored values, so a
 * blank field erases a working secret rather than leaving it untouched. On CREATE
 * a blank value is legal (an intentionally empty var), which is why this reports
 * names instead of deciding policy.
 */
export function blankValueNames(env: Record<string, string>): string[] {
    return Object.keys(env).filter(name => !env[name]);
}

/**
 * Collapse editor rows into the `{NAME: value}` bundle the credential stores.
 * Throws on an invalid or duplicate name — never silently drops one, matching the
 * backend's fail-loud stance (a missing variable surfaces later as an agent that
 * inexplicably can't reach an API).
 */
export function rowsToEnv(rows: EnvRow[]): Record<string, string> {
    const env: Record<string, string> = {};
    for (const row of rows) {
        const name = row.key.trim();
        if (!name && !row.value) continue; // untouched blank row
        if (!name) throw new Error('Every value needs a variable name.');
        const invalid = validateEnvName(name);
        if (invalid) throw new Error(invalid);
        if (name in env) throw new Error(`"${name}" is set more than once.`);
        env[name] = row.value;
    }
    return env;
}
