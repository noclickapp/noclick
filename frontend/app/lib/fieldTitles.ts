// A step's config field as a person reads it: the field's title from the node's schema ("calendar_id" → "calendar"),
// or for the keys the canvas keeps with no schema of their own, what they mean ("agent_tool_operations" → "its
// actions"). The steps' schemas load on first use off the panel's path; until then a key reads as its words.
import { useEffect, useMemo } from 'react';
import { proxy, useSnapshot } from 'valtio';

type Schemas = typeof import('~/utils/nodeSchemas');

// Keys whose schema title doesn't say what they are: the canvas's own (no Pydantic field, so no title), and the ones
// every step has, whose title in a schema is one operation's name.
const CANVAS_KEYS: Record<string, string> = {
    agent_tool_operations: 'its actions',
    agent_sandbox_repos: 'its repos',
    agent_env_requested: 'its environment variables',
    show_in_interface: 'where it shows',
    operation: 'what it does',
    label: 'its name',
};

const state = proxy({ version: 0 });
let schemas: Schemas | null = null;
let schemasModule: Promise<Schemas> | null = null;

/** Loads the schemas of the steps of `types`. */
function load(types: Iterable<string | undefined>): Promise<void> {
    schemasModule ??= import('~/utils/nodeSchemas');
    return schemasModule.then(async (loaded) => {
        schemas = loaded;
        await loaded.loadNodeSchemas(types);
        state.version += 1;
    });
}

/** A config key as words: "agent_tool_operations" → "agent tool operations". */
export const fieldWords = (key: string) => key.replace(/[_-]+/g, ' ').replace(/([a-z])([A-Z])/g, '$1 $2').toLowerCase().trim();

/** "Calendar ID" → "calendar ID": lowercase a title's first word unless it's an acronym. */
const asWords = (title: string) => (/^[A-Z][a-z]/.test(title) ? title.charAt(0).toLowerCase() + title.slice(1) : title);

function schemaTitle(schema: unknown, key: string): string | undefined {
    const seen = new Set<unknown>();
    const walk = (node: unknown): string | undefined => {
        if (!node || typeof node !== 'object' || seen.has(node)) return undefined;
        seen.add(node);
        const properties = (node as { properties?: Record<string, { title?: unknown }> }).properties;
        const title = properties?.[key]?.title;
        if (typeof title === 'string' && title) return title;
        for (const value of Object.values(node)) {
            const found = walk(value);
            if (found) return found;
        }
        return undefined;
    };
    return walk(schema);
}

/** A field of a step of `nodeType`, in words. */
export function fieldTitle(nodeType: string | undefined, key: string): string {
    if (CANVAS_KEYS[key]) return CANVAS_KEYS[key];
    const title =
        schemas && nodeType && schemas.nodeSchemasLoaded([nodeType]) ? schemaTitle(schemas.getNodeSchema(nodeType), key) : undefined;
    return title ? asWords(title) : fieldWords(key);
}

/** Loads the schemas the titles of `types`' fields come from, and re-renders once they're in. */
export function useFieldTitles(types: Iterable<string | undefined>): boolean {
    const { version } = useSnapshot(state);
    const key = useMemo(() => [...new Set([...types].filter((type): type is string => !!type))].sort().join(','), [types]);
    useEffect(() => {
        if (key) void load(key.split(','));
    }, [key]);
    return !key || (version > 0 && !!schemas?.nodeSchemasLoaded(key.split(',')));
}

/** The schemas the titles of `types`' fields come from, loaded (tests, and anything that can wait for them). */
export const loadFieldTitles = load;
