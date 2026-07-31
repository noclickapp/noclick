// Detects whether a workflow starts on automatic event triggers (webhook,
// inbound email, schedule, or integration trigger operations like "new row on
// Sheets") rather than a manual Run trigger. The canvas uses this so that
// pressing Run on a purely trigger-driven workflow explains how it actually
// starts, instead of silently doing a confusing one-off test run.
import { getNodeIconMeta } from '~/lib/nodeIconRegistry';
import { getTriggerOperations, isTriggerSource, resolveNodeType } from '~/utils/nodeSchemas';
import { getFieldsForOption } from '~/utils/schemaFieldExtractor';
import { getCredentialEmail } from '~/utils/credentialAutoSelect';
import { EMAIL_DOMAIN } from '~/components/workflow/EmailTriggerField';
import { describeSchedule, getScheduleEntries, isTimeOfDaySchedule } from '~/utils/scheduleFormat';

/** A configured specific the trigger listens to — e.g. the spreadsheet/sheet it
 *  watches, or the address/URL that fires it. */
export interface TriggerParam {
    label: string;
    value: string;
    /** Render the value monospace + copyable (addresses, URLs). */
    mono?: boolean;
    /** When set, the value also gets an "open in a new tab" link (e.g. a form
     *  trigger's hosted page — pressing Run won't submit it, so this is how the
     *  user actually exercises the form). */
    href?: string;
}

export interface WorkflowTrigger {
    nodeId: string;
    nodeType: string;
    /** Service / trigger name, e.g. "Gmail", "Webhook", "Schedule". */
    title: string;
    /** User-given node label, if any (shown as a subtle tag). */
    label: string;
    /** Human-readable "runs when …" description. */
    description: string;
    /** The specifics this trigger is configured to listen to. */
    params: TriggerParam[];
    iconHtml?: string;
    iconColor?: string;
}

// The dedicated trigger node types (trigger-* plus the unified form node) carry
// no x-is-trigger operation to read a description from, so describe them here.
const DEDICATED_TRIGGER_DESCRIPTIONS: Record<string, string> = {
    'trigger-webhook': "Runs when an HTTP request hits this workflow's webhook URL.",
    'trigger-email': "Runs when an email arrives at this workflow's address.",
    'trigger-cron': 'Runs automatically on a recurring schedule.',
    'interface-form': 'Runs when someone submits this form.',
};

// The manual Run trigger is the only entry point a user starts by pressing Run,
// so it suppresses the trigger-info prompt. A form node is NOT manual here:
// pressing Run won't submit the form, so the prompt explains it (and links to the
// hosted form) instead of silently running with no input.
const MANUAL_ENTRY_TYPES = new Set(['trigger-run']);

interface CanvasNode {
    id: string;
    type?: string;
    data?: Record<string, unknown>;
}

function nodeOperation(node: CanvasNode): string | undefined {
    const data = node.data;
    const nested = (data?.config as { operation?: string } | undefined)?.operation;
    return (data?.operation as string | undefined) ?? nested;
}

function strv(v: unknown): string {
    return typeof v === 'string' ? v.trim() : '';
}

// Schema descriptions sometimes lead with the jargon prefix "Trigger:" — drop it
// and capitalize so the popup reads in plain language.
function cleanDescription(desc: string): string {
    const d = desc.trim().replace(/^trigger\s*[:\-–]\s*/i, '');
    return d ? d.charAt(0).toUpperCase() + d.slice(1) : d;
}

// Plain config fields that are plumbing, not "what the trigger listens to".
// (Most plumbing is caught structurally — by widget / type / boolean-enum below —
// so this only needs the stragglers that look like free-text filters.)
const PLUMBING_FIELD_NAMES = new Set(['timezone']);

function isBooleanEnum(prop: { enum?: unknown }): boolean {
    return (
        Array.isArray(prop.enum) &&
        prop.enum.every(v => ['true', 'false', 'yes', 'no'].includes(String(v)))
    );
}

function prettyEnum(v: string): string {
    const s = v.replace(/[_-]+/g, ' ').trim();
    return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
}

// The display value for one config field, or null if it isn't a user-meaningful
// "what does this trigger watch" field. Resource selectors (x-dynamic-options)
// resolve to the label persisted by DynamicOptionsField (`<field>__label`); plain
// string/array filter fields (Gmail query, Jira JQL, channels) surface as-is.
// Widget-driven fields (webhook URL, schedule), numbers, and yes/no toggles are
// plumbing and skipped.
function fieldDisplayValue(
    prop: Record<string, unknown>,
    key: string,
    config: Record<string, unknown>,
): string | null {
    const raw = config[key];
    if (prop['x-dynamic-options']) {
        const v = strv(raw);
        if (!v || v.includes('{{')) return null;
        return strv(config[`${key}__label`]) || v;
    }
    if (prop['ui:widget'] || PLUMBING_FIELD_NAMES.has(key) || isBooleanEnum(prop)) return null;
    if (Array.isArray(raw)) {
        const items = raw.filter((x): x is string => typeof x === 'string' && !!x.trim()).map(x => x.trim());
        return items.length ? items.join(', ') : null;
    }
    const v = strv(raw);
    if (!v || v.includes('{{') || (prop.type && prop.type !== 'string')) return null;
    return Array.isArray(prop.enum) ? prettyEnum(v) : v;
}

/** The connected account email for a node's credential (OAuth metadata.email),
 *  e.g. the Gmail mailbox a poll trigger watches. Reads the synchronous cache. */
function accountEmail(credentialIds: Record<string, unknown> | undefined): string | undefined {
    if (!credentialIds) return undefined;
    for (const [k, v] of Object.entries(credentialIds)) {
        if (k === 'credential_type' || typeof v !== 'string' || !v) continue;
        const email = getCredentialEmail(v);
        if (email) return email;
    }
    return undefined;
}

/**
 * The configured specifics a trigger listens to, resolved to human-readable
 * values. Dedicated triggers expose their fire address (email / webhook URL);
 * integration triggers surface the connected account (e.g. the Gmail mailbox
 * being polled), their resource selectors, and filter fields.
 */
function getTriggerParams(
    nodeType: string,
    operation: string | undefined,
    config: Record<string, unknown>,
    credentialIds: Record<string, unknown> | undefined,
): TriggerParam[] {
    if (nodeType === 'trigger-email') {
        const lp = strv(config.local_part);
        const addr = strv(config.email_address) || (lp ? `${lp}@${EMAIL_DOMAIN}` : '');
        return addr ? [{ label: 'Send an email to', value: addr, mono: true }] : [];
    }
    if (nodeType === 'trigger-webhook') {
        const url = strv(config.webhook_url);
        return url ? [{ label: 'Send a request to', value: url, mono: true }] : [];
    }
    if (nodeType === 'interface-form') {
        // The hosted form page (load-value populated). Surfaced as an openable link
        // so Run, which can't submit the form, points the user to where it lives.
        const url = strv(config.webhook_url);
        return url.startsWith('http') ? [{ label: 'Form URL', value: url, mono: true, href: url }] : [];
    }
    if (nodeType === 'trigger-cron') {
        // Surface when each configured schedule actually fires, plus the timezone
        // when a schedule is time-of-day based (so "9:00 AM" is unambiguous).
        const entries = getScheduleEntries(config);
        const params: TriggerParam[] = [];
        for (const s of entries) {
            const phrase = describeSchedule(s);
            if (phrase) params.push({ label: 'Schedule', value: phrase.charAt(0).toUpperCase() + phrase.slice(1) });
        }
        const tz = strv(config.timezone);
        if (tz && entries.some(isTimeOfDaySchedule)) params.push({ label: 'Timezone', value: tz });
        return params;
    }

    const params: TriggerParam[] = [];
    const account = accountEmail(credentialIds);
    if (account) params.push({ label: 'Account', value: account, mono: true });
    for (const f of getFieldsForOption(nodeType, undefined, operation)) {
        // The operation discriminator isn't always stamped ui:hidden, so guard it
        // explicitly rather than relying on getFieldsForOption to drop it.
        if (f.key === 'operation') continue;
        const value = fieldDisplayValue(f.prop, f.key, config);
        if (value !== null) params.push({ label: f.prop.title || f.key, value });
    }
    return params;
}

/** Automatic (event-driven) triggers configured on the canvas, skipping disabled nodes. */
export function getAutomaticTriggers(nodes: CanvasNode[]): WorkflowTrigger[] {
    const out: WorkflowTrigger[] = [];
    for (const node of nodes) {
        const type = node.type ? resolveNodeType(node.type) : node.type;
        if (!type || MANUAL_ENTRY_TYPES.has(type) || node.data?.disabled) continue;
        const operation = nodeOperation(node);
        if (!isTriggerSource(type, operation)) continue;

        const meta = getNodeIconMeta(type);
        const label = (node.data?.label as string | undefined) || '';
        const config = (node.data?.config as Record<string, unknown> | undefined) ?? {};
        const credentialIds = node.data?.credentialIds as Record<string, unknown> | undefined;
        let description = 'Runs automatically when triggered.';
        if (DEDICATED_TRIGGER_DESCRIPTIONS[type]) {
            description = DEDICATED_TRIGGER_DESCRIPTIONS[type];
        } else if (operation) {
            const op = getTriggerOperations(type).find(o => o.operation === operation);
            description = cleanDescription(op?.description || op?.displayName || description);
        }

        out.push({
            nodeId: node.id,
            nodeType: type,
            title: meta?.label || label || type,
            label,
            description,
            params: getTriggerParams(type, operation, config, credentialIds),
            iconHtml: meta?.iconHtml,
            iconColor: meta?.iconColor,
        });
    }
    return out;
}

/** Whether the workflow has a manual / interactive entry point (Run trigger or form). */
export function hasManualEntry(nodes: CanvasNode[]): boolean {
    return nodes.some(n => n.type && MANUAL_ENTRY_TYPES.has(n.type));
}

/**
 * The triggers to explain when Run is pressed, or null to run normally. Returns
 * non-null only when the workflow starts purely on automatic events with no
 * manual entry point — the case where a plain run would surprise the user.
 */
export function getTriggerRunPrompt(nodes: CanvasNode[]): WorkflowTrigger[] | null {
    if (hasManualEntry(nodes)) return null;
    const triggers = getAutomaticTriggers(nodes);
    return triggers.length > 0 ? triggers : null;
}
