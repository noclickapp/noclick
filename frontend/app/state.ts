import * as Y from 'yjs';
import { proxy, subscribe } from 'valtio';
import { bind } from 'valtio-yjs';
import { socketReceiver } from './lib/socket-receiver';
import { SocketIOProvider } from './lib/y-socketio';
import { onSocketEvent } from './lib/socket-receiver';
import { valtioCache } from './lib/indexeddb';
import { valtioSessionCache } from './lib/session-cache';
import type { Socket } from 'socket.io-client';

import type { ServerToClientEvents, ClientToServerEvents } from '~/types/socket-events.generated';

// Self explanatory, individual component states
interface ComponentState {
    path: string;
    state: Record<string, unknown>;
    subcomponents: Record<string, ComponentState>;
}

// For server responses
interface StateResponse {
    path: string | null;
    key: string | null;
    value: unknown;
    processed?: boolean;
}

// This is the main app-wide state object
interface AppState {
    path: string;
    state: Record<string, unknown>;
    subcomponents: Record<string, ComponentState>;
    data: Record<string, unknown>;
    responses?: StateResponse[];
    // Add index signature to allow dynamic properties
    [key: string]: unknown;
}

const ydoc = new Y.Doc();

// Sync yjs state with the main server communication socket
let currentProvider: SocketIOProvider | null = null;

// Track binding state to ensure it only happens once
let bindingComplete = false;

// Variable to hold the unsubscribe function for the persistence subscription
let persistenceUnsubscribe: (() => void) | null = null;

// Helper to extract flat IndexedDB keys from nested YJS structure
// Traverses: subcomponents -> component -> subcomponents -> component -> state -> key
// Produces: "component/component:key"
function extractStateKeys(obj: any, pathParts: string[] = []): Array<{ idbKey: string; yjsPath: string[]; value: any }> {
    const results: Array<{ idbKey: string; yjsPath: string[]; value: any }> = [];

    if (!obj || typeof obj !== 'object') return results;

    // Check if this level has a 'state' object with keys
    if (obj.state && typeof obj.state === 'object') {
        for (const [key, value] of Object.entries(obj.state)) {
            // Build IndexedDB key: "path/parts:key"
            const valtioPath = pathParts.join('/');
            const idbKey = valtioPath ? `${valtioPath}:${key}` : key;

            // Build YJS path for setting later
            const yjsPath = ['subcomponents', ...pathParts.flatMap(p => ['subcomponents', p]).slice(1), 'state', key];

            results.push({ idbKey, yjsPath, value });
        }
    }

    // Recursively traverse subcomponents
    if (obj.subcomponents && typeof obj.subcomponents === 'object') {
        for (const [componentName, componentData] of Object.entries(obj.subcomponents)) {
            results.push(...extractStateKeys(componentData, [...pathParts, componentName]));
        }
    }

    return results;
}

// Set up cache restoration listener immediately (before socket connects)
// This ensures we're ready to receive the event as soon as the backend sends it
let cacheRestored = false;
const unsubscribeCacheRestore = onSocketEvent('cache_valtio:state', async (data: { state_update: number[], cache_timestamp: number }) => {
    if (cacheRestored) {
        console.log('[State] Cache already restored, ignoring duplicate event');
        return;
    }

    console.log('[State] Received cached state from server, applying with timestamp-based merge...');
    console.log('[State] Cache data size:', data.state_update.length, 'bytes');
    console.log('[State] Remote cache timestamp:', data.cache_timestamp);

    try {
        // Parse remote YJS update into a temporary document
        const remoteUpdate = new Uint8Array(data.state_update);
        const remoteDoc = new Y.Doc();
        Y.applyUpdate(remoteDoc, remoteUpdate);
        const remoteMap = remoteDoc.getMap('state');
        const remoteData = remoteMap.toJSON();

        // Get the current YJS map (might have some local edits already)
        const localMap = ydoc.getMap('state');

        // Extract all state keys from the nested structure
        const stateEntries = extractStateKeys(remoteData);
        console.log(`[State] Found ${stateEntries.length} state entries in remote cache`);

        // Snapshot all sessionStorage and IndexedDB timestamps BEFORE starting comparisons (prevent race conditions)
        const sessionSnapshots = new Map<string, { timestamp: number; value: any }>();
        const idbSnapshots = new Map<string, { timestamp: number; value: any }>();
        await Promise.all(
            stateEntries.map(async ({ idbKey }) => {
                const [sessionData, idbData] = await Promise.all([
                    valtioSessionCache.getWithMetadata(idbKey),
                    valtioCache.getWithMetadata(idbKey)
                ]);

                if (sessionData) {
                    sessionSnapshots.set(idbKey, { timestamp: sessionData.timestamp, value: sessionData.value });
                }
                if (idbData) {
                    idbSnapshots.set(idbKey, { timestamp: idbData.timestamp, value: idbData.value });
                }
            })
        );

        // Now perform selective merge based on timestamp comparison
        // Priority: sessionStorage (tab-specific) > timestamp comparison (IndexedDB vs Remote)
        for (const { idbKey, yjsPath, value: remoteValue } of stateEntries) {
            const sessionSnapshot = sessionSnapshots.get(idbKey);
            const idbSnapshot = idbSnapshots.get(idbKey);
            const sessionTimestamp = sessionSnapshot?.timestamp ?? 0;
            const idbTimestamp = idbSnapshot?.timestamp ?? 0;
            const remoteTimestamp = data.cache_timestamp;

            // Helper to preview values (truncate if too long)
            const previewValue = (val: any) => {
                const str = JSON.stringify(val);
                return str.length > 100 ? str.substring(0, 100) + '...' : str;
            };

            if (sessionSnapshot) {
                // SessionStorage exists → always use it (tab-specific wins)
                console.log(`[State] 🔵 ${idbKey}: Using tab-specific sessionStorage (${sessionTimestamp})`, previewValue(sessionSnapshot.value));
                setNestedValue(localMap, yjsPath, sessionSnapshot.value);
            } else if (!idbSnapshot) {
                // No local data at all → use remote
                console.log(`[State] 📥 ${idbKey}: No local data, using remote`, previewValue(remoteValue));
                setNestedValue(localMap, yjsPath, remoteValue);
            } else if (idbTimestamp > remoteTimestamp) {
                // IndexedDB is newer → keep IndexedDB
                console.log(`[State] ⬆️ ${idbKey}: IndexedDB newer (${idbTimestamp} > ${remoteTimestamp}), keeping local`, previewValue(idbSnapshot.value));
                setNestedValue(localMap, yjsPath, idbSnapshot.value);
            } else {
                // Remote is newer or equal → use remote
                console.log(`[State] ⬇️ ${idbKey}: Remote newer or equal (${remoteTimestamp} >= ${idbTimestamp}), using remote`, previewValue(remoteValue));
                setNestedValue(localMap, yjsPath, remoteValue);
            }
        }

        console.log('[State] Successfully merged cached state to YDoc');

        // Now bind valtio to YJS - valtio will pick up the merged state from YDoc
        bindCachedbToYJS();

        cacheRestored = true;
    } catch (error) {
        console.error('[State] Failed to apply cached state:', error);
        // Even if cache restoration fails, we should still bind
        bindCachedbToYJS();
    }
});

// Helper to recursively convert plain JS objects/arrays to YJS structures
// This ensures proper YJS synchronization for nested data
function toYjsStructure(value: any): any {
    if (value === null || value === undefined) {
        return value;
    }

    // Handle arrays - convert to Y.Array with all items in one operation
    if (Array.isArray(value)) {
        const yArray = new Y.Array();
        const yjsItems = value.map(item => toYjsStructure(item));
        yArray.push(yjsItems);
        return yArray;
    }

    // Handle plain objects - convert to Y.Map
    if (typeof value === 'object' && value.constructor === Object) {
        const yMap = new Y.Map();
        Object.entries(value).forEach(([key, val]) => {
            yMap.set(key, toYjsStructure(val));
        });
        return yMap;
    }

    // Primitives (string, number, boolean) and other types pass through
    return value;
}

// Helper to set a value at a nested YJS path
// Navigate through YJS Maps without clearing to avoid race conditions
function setNestedValue(ymap: Y.Map<any>, path: string[], value: any) {
    // Navigate through nested Y.Maps, creating them as needed
    let current: Y.Map<any> = ymap;

    for (let i = 0; i < path.length - 1; i++) {
        const key = path[i];
        let next = current.get(key);

        // Create nested map if it doesn't exist or isn't a map
        if (!next || !(next instanceof Y.Map)) {
            next = new Y.Map();
            current.set(key, next);
        }

        current = next as Y.Map<any>;
    }

    // Convert plain objects/arrays to YJS structures before setting
    // This ensures nested data is properly synchronized
    const finalKey = path[path.length - 1];
    const yjsValue = toYjsStructure(value);
    current.set(finalKey, yjsValue);
}

socketReceiver.subscribeConnection('API', (state) => {
    if (state.status === 'connected') {
        // Add a small delay to ensure socket is fully ready
        setTimeout(() => {
            // Clean up existing provider if there is one
            if (currentProvider) {
                currentProvider.destroy();
            }
            // Create and store new provider
            const socket = socketReceiver.getSocket('API');
            if (socket?.connected) {
                currentProvider = new SocketIOProvider(ydoc, socket);
                currentProvider.connect();
            }
            
            // If no cache was restored after 1s, bind anyway
            // This handles the case where there's no cached state
            setTimeout(() => {
                if (!cacheRestored && !bindingComplete) {
                    console.log('[State] No cache received, binding cachedb to YJS...');
                    bindCachedbToYJS();
                }
            }, 1000);
        }, 100);
    } else if (state.status === 'disconnected') {
        // Clean up provider on disconnection
        if (currentProvider) {
            currentProvider.destroy();
            currentProvider = null;
        }

        // Clean up persistence subscription to prevent memory leaks
        if (persistenceUnsubscribe) {
            persistenceUnsubscribe();
            persistenceUnsubscribe = null;
        }

        // Reset flags on disconnect so reconnection works properly
        cacheRestored = false;
        bindingComplete = false;
    }
});

// Primary state: cachedb - YJS-synced state for backend persistence (100ms debounced)
// This is what most existing components use
const ymap = ydoc.getMap('state');
const cachedb: AppState = proxy({
    path: '',
    state: {},
    subcomponents: {},
    data: {}, // Initialize data object
});

// Function to bind cachedb to YJS and set up granular IndexedDB persistence
function bindCachedbToYJS() {
    if (!bindingComplete) {
        bind(cachedb, ymap);

        // IMPORTANT: Set up granular persistence subscription AFTER bind()
        // This ensures we're subscribing to the bound proxy, not the original
        persistenceUnsubscribe = subscribe(cachedb, (ops) => {
            ops.forEach(op => {
                const [operation, path, value] = op;

                // Transform ops path to match useCachedValtioState format
                // ['subcomponents', 'dashboard', 'subcomponents', 'vite_browser', 'state', 'viteApps'] -> 'dashboard/vite_browser:viteApps'
                if (path.length >= 3 && path[0] === 'subcomponents' && path[path.length - 2] === 'state') {
                    const valtioPath = path.slice(1, -2).filter(part => part !== 'subcomponents').join('/');
                    const key = String(path[path.length - 1]);
                    const idbKey = `${valtioPath}:${key}`;

                    if (operation === 'set') {
                        // Serialize the value to avoid DataCloneError with proxy objects
                        const serializedValue = JSON.parse(JSON.stringify(value));
                        // Write to both storages with same timestamp
                        valtioSessionCache.set(idbKey, serializedValue);
                        valtioCache.set(idbKey, serializedValue);
                    } else if (operation === 'delete') {
                        valtioSessionCache.delete(idbKey);
                        valtioCache.delete(idbKey);
                    }
                }
            });
        });

        bindingComplete = true;
    }
}

// Secondary state: local-only valtio state for UI-specific data (not synced)
const state: AppState = proxy({
    path: '',
    state: {},
    subcomponents: {},
    data: {}, // Initialize data object
});

// Cached state function - uses cachedb for backend sync
function getCachedComponentValtio(path: string): ComponentState {
    const pathParts = path.split('/').filter(Boolean);
    let currentProxy: ComponentState = cachedb;

    for (const part of pathParts) {
        // Ensure subcomponents exists (can be missing after YJS binding syncs partial state)
        if (!currentProxy.subcomponents) {
            currentProxy.subcomponents = {};
        }
        if (!currentProxy.subcomponents[part]) {
            currentProxy.subcomponents[part] = {
                path: `${currentProxy.path}/${part}`,
                state: {},
                subcomponents: {},
            };
        }
        currentProxy = currentProxy.subcomponents[part];
    }

    return currentProxy;
}

// Local state function - uses local state (no backend sync) - DEFAULT
function getLocalComponentValtio(path: string): ComponentState {
    const pathParts = path.split('/').filter(Boolean);
    let currentProxy: ComponentState = state;

    for (const part of pathParts) {
        // Ensure subcomponents exists (defensive check for consistency)
        if (!currentProxy.subcomponents) {
            currentProxy.subcomponents = {};
        }
        if (!currentProxy.subcomponents[part]) {
            currentProxy.subcomponents[part] = {
                path: `${currentProxy.path}/${part}`,
                state: {},
                subcomponents: {},
            };
        }
        currentProxy = currentProxy.subcomponents[part];
    }

    return currentProxy;
}
export {
    state,
    cachedb,
    getCachedComponentValtio,  // For synced state when needed
    getLocalComponentValtio,  // For local state (DEFAULT)
};
