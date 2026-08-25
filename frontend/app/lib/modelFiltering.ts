// Shared model-list filtering/sorting for the model pickers (chat ModelDropdown,
// canvas ModelPickerModal). Centralizes search normalization, provider/feature
// filtering, dedup, favorites ordering, and priority pinning so every picker
// surface resolves the same query to the same list.

import type { Model } from '~/types/model';
import type { ModelProvider } from '~/types/provider';

/** Strip separators/punctuation and lowercase so "gpt 4o" matches "gpt-4o". */
export function normalizeForSearch(str: string): string {
    return str.toLowerCase().replace(/[-_.:\s/\\]/g, '');
}

/** Last path segment of a model id — the human-friendly short name. */
export function modelShortName(modelId: string): string {
    const parts = modelId.split('/');
    return parts[parts.length - 1];
}

export interface ModelFilterOptions {
    searchQuery: string;
    selectedProviders: Set<ModelProvider>;
    /** Capability keys (e.g. 'imageAnalysis') the model must all have. */
    selectedFeatures: Set<string>;
    viewMode: 'favorites' | 'all';
    userFavorites: string[];
    /** Model ids pinned to the top in 'all' view (e.g. CLI agents). */
    priorityModelIds?: readonly string[];
    /** Float $0-priced models above paid ones (below any priority pins),
     *  preserving order inside each band. The agent model picker opts in;
     *  surfaces like the demo chat keep the provider's native ordering. */
    freeFirst?: boolean;
}

export function filterAndSortModels<T extends Model>(
    models: T[],
    opts: ModelFilterOptions,
): T[] {
    const {
        searchQuery,
        selectedProviders,
        selectedFeatures,
        viewMode,
        userFavorites,
        priorityModelIds,
    } = opts;
    const normalizedQuery = normalizeForSearch(searchQuery);
    const lowerQuery = searchQuery.toLowerCase();

    const filtered = (models || []).filter((model) => {
        if (viewMode === 'favorites' && !userFavorites.includes(model.id)) {
            return false;
        }
        if (selectedProviders.size > 0 && !selectedProviders.has(model.provider)) {
            return false;
        }
        if (selectedFeatures.size > 0) {
            const caps = model.capabilities as Record<string, boolean | undefined> | undefined;
            const hasAll = Array.from(selectedFeatures).every((feature) => caps?.[feature]);
            if (!hasAll) return false;
        }
        // Normalized match first ("gpt 4o" → "gpt-4o"), raw substring as
        // backup. Free models also answer to "free" — their ids often don't
        // carry the word (OpenCode Zen's glm-5 vs OpenRouter's :free suffix).
        const haystack = model.free ? `${model.id} free` : model.id;
        return (
            normalizeForSearch(haystack).includes(normalizedQuery) ||
            haystack.toLowerCase().includes(lowerQuery)
        );
    });

    // Deduplicate by model id (keep first occurrence).
    const seen = new Set<string>();
    const deduplicated = filtered.filter((model) => {
        if (seen.has(model.id)) return false;
        seen.add(model.id);
        return true;
    });

    // Favorites view follows the user's own favorite ordering.
    if (viewMode === 'favorites') {
        return deduplicated.sort(
            (a, b) => userFavorites.indexOf(a.id) - userFavorites.indexOf(b.id),
        );
    }

    // Band ordering, stable inside each band: priority pins (e.g. CLI agents)
    // first, then — when freeFirst — $0 models above paid ones.
    const hasPriority = !!priorityModelIds && priorityModelIds.length > 0;
    if (!hasPriority && !opts.freeFirst) return deduplicated;
    const priorityIndex = (id: string) => {
        const i = hasPriority ? priorityModelIds.indexOf(id) : -1;
        return i === -1 ? Number.MAX_SAFE_INTEGER : i;
    };
    return [...deduplicated].sort((a, b) => {
        const byPriority = priorityIndex(a.id) - priorityIndex(b.id);
        if (byPriority !== 0) return byPriority;
        if (!opts.freeFirst) return 0;
        return Number(Boolean(b.free)) - Number(Boolean(a.free));
    });
}
