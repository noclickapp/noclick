/**
 * useConversationCache Hook
 *
 * Provides local caching for conversation data to enable instant navigation.
 * Uses IndexedDB for persistence without Redis sync (cache data is session-local).
 *
 * Key features:
 * - Cache conversations by ID for instant navigation
 * - TTL-based cache invalidation (5 minutes)
 * - No Redis sync (skipRedisSync: true) to avoid overhead
 */

import { useCallback } from 'react';
import { useCachedValtioState } from './useCachedValtioState';
import { Message } from '~/components/chat/types';

// Cache entry with metadata
interface CachedConversation {
    messages: Message[];
    timestamp: number;
    // Store raw backend format for consistency
    rawMessages?: any[];
}

// Cache configuration
const CACHE_TTL_MS = 5 * 60 * 1000; // 5 minutes
const MAX_CACHE_SIZE = 20; // Maximum conversations to cache

export function useConversationCache() {
    // Use cached valtio state WITHOUT Redis sync for local-only caching
    const [cache, setCache] = useCachedValtioState<Record<string, CachedConversation>>(
        'branching',
        'conversationCache',
        {},
        true // skipRedisSync - no need to sync branch cache to Redis
    );

    /**
     * Get a conversation from cache if it exists and is fresh
     */
    const getFromCache = useCallback((conversationId: string): CachedConversation | null => {
        const entry = cache[conversationId];
        if (!entry) {
            return null;
        }

        // Check if cache entry is still fresh
        const age = Date.now() - entry.timestamp;
        if (age > CACHE_TTL_MS) {
            console.log(`[ConvCache] Cache expired for ${conversationId} (age: ${age}ms)`);
            return null;
        }

        console.log(`[ConvCache] Cache hit for ${conversationId} (age: ${age}ms)`);
        return entry;
    }, [cache]);

    /**
     * Add or update a conversation in cache
     */
    const addToCache = useCallback((
        conversationId: string,
        messages: Message[],
        rawMessages?: any[]
    ) => {
        console.log(`[ConvCache] Caching conversation ${conversationId} with ${messages.length} messages`);

        setCache(prev => {
            const newCache = { ...prev };

            // Add new entry
            newCache[conversationId] = {
                messages,
                timestamp: Date.now(),
                rawMessages
            };

            // Prune old entries if cache is too large
            const entries = Object.entries(newCache);
            if (entries.length > MAX_CACHE_SIZE) {
                // Sort by timestamp (oldest first) and remove oldest
                entries.sort((a, b) => a[1].timestamp - b[1].timestamp);
                const toRemove = entries.slice(0, entries.length - MAX_CACHE_SIZE);
                for (const [id] of toRemove) {
                    delete newCache[id];
                    console.log(`[ConvCache] Pruned old entry: ${id}`);
                }
            }

            return newCache;
        });
    }, [setCache]);

    /**
     * Invalidate a specific conversation in cache
     * Call this when a conversation is modified (e.g., new messages added)
     */
    const invalidateCache = useCallback((conversationId: string) => {
        console.log(`[ConvCache] Invalidating cache for ${conversationId}`);
        setCache(prev => {
            if (!prev[conversationId]) return prev;
            const newCache = { ...prev };
            delete newCache[conversationId];
            return newCache;
        });
    }, [setCache]);

    /**
     * Clear all cached conversations
     */
    const clearCache = useCallback(() => {
        console.log('[ConvCache] Clearing all cached conversations');
        setCache({});
    }, [setCache]);

    return {
        getFromCache,
        addToCache,
        invalidateCache,
        clearCache
    };
}
