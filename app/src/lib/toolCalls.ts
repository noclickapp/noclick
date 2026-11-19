// An agent's tool calls in one turn, read back out of the turn's step rows: the live frames and the restored
// transcript both carry each call as "Calling {tool}({args})" with its result as the row's detail, each a bounded
// prefix of the JSON. A chat draws its inline cards from these, so a card shows exactly what the tool did.
import { parsePartialJson } from '@/lib/partialJson';

export type JsonObject = Record<string, unknown>;

/** One row of a turn's activity: a status it passed ("Starting sandbox…") or a tool it called. A row is keyed by its
 *  id, so the frame that finishes a call updates the row its start drew. */
export interface TurnStep {
    id: string;
    /** As it was first seen: "Calling linear__create_issue({…})", "Starting sandbox…". */
    title: string;
    /** A tool call's result, as the frame that finished it previewed it. */
    detail?: string;
    status: 'in_progress' | 'completed';
    kind: 'status' | 'tool';
    startedAt: number;
    endedAt?: number;
}

export interface CoordinatorToolCall {
    id: string;
    tool: string;
    /** The arguments it was called with, as far as they arrived whole. */
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

export function coordinatorToolCalls(steps: readonly TurnStep[] | undefined): CoordinatorToolCall[] {
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

/** The ids a call's answer names what it's about by: the approval it held, the operation it started, the agent it
 *  handed work to (and that agent's task), each once. */
export function cardRefsOf(call: CoordinatorToolCall): string[] {
    const response = obj(call.result, 'response');
    const ids = [str(call.result, 'approval_id'), str(call.result, 'operation_id'), str(call.result, 'job_id'), str(response, 'operation_id'), str(response, 'agent_id'), str(response, 'job_id')];
    if (str(response, 'object') === 'agent') ids.push(str(response, 'id'));
    return [...new Set(ids.filter((id): id is string => !!id))];
}

export function list(value: JsonObject | undefined, key: string): unknown[] {
    const v = value?.[key];
    return Array.isArray(v) ? v : [];
}
