// The coordinator's tool calls in one turn, read back out of the turn's step rows: the live frames and the restored
// transcript both carry each call as "Calling {tool}({args})" with its result as the row's detail, each a bounded
// prefix of the JSON. The chat draws its inline cards from these, so a card shows exactly what the tool did.
import type { AgentChatStep } from '~/hooks/useAgentChat';
import { parsePartialJson } from '~/lib/partialJson';

export type JsonObject = Record<string, unknown>;

export interface CoordinatorToolCall {
    id: string;
    tool: string;
    /** The arguments the coordinator called it with, as far as they arrived whole. */
    args: JsonObject;
    /** What it answered, once it has, as far as that arrived whole. */
    result?: JsonObject;
    running: boolean;
    startedAt: number;
}

const CALL = /^Calling ([\w.-]+)\(([\s\S]*)$/;

function asObject(value: unknown): JsonObject | undefined {
    return value && typeof value === 'object' && !Array.isArray(value) ? (value as JsonObject) : undefined;
}

export function coordinatorToolCalls(steps: readonly AgentChatStep[] | undefined): CoordinatorToolCall[] {
    const calls: CoordinatorToolCall[] = [];
    for (const step of steps ?? []) {
        if (step.kind !== 'tool') continue;
        const m = CALL.exec(step.title);
        if (!m) continue;
        // A whole title ends with the call's closing paren; a clipped one ends wherever the cut fell.
        const argsText = m[2].endsWith(')') ? m[2].slice(0, -1) : m[2];
        calls.push({
            id: step.id,
            tool: m[1],
            args: asObject(parsePartialJson(argsText)) ?? {},
            result: step.detail ? asObject(parsePartialJson(step.detail)) : undefined,
            running: step.status === 'in_progress',
            startedAt: step.startedAt,
        });
    }
    return calls;
}

/** A tool answer that says it didn't do the thing: `success: false` or an `error`. */
export function failed(result: JsonObject | undefined): boolean {
    return !!result && (result.success === false || (typeof result.error === 'string' && !!result.error));
}

export function str(value: JsonObject | undefined, key: string): string | undefined {
    const v = value?.[key];
    return typeof v === 'string' && v ? v : undefined;
}

export function num(value: JsonObject | undefined, key: string): number | undefined {
    const v = value?.[key];
    return typeof v === 'number' && Number.isFinite(v) ? v : undefined;
}

export function obj(value: JsonObject | undefined, key: string): JsonObject | undefined {
    return asObject(value?.[key]);
}

export function list(value: JsonObject | undefined, key: string): unknown[] {
    const v = value?.[key];
    return Array.isArray(v) ? v : [];
}
