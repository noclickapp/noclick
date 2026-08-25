/**
 * Profiling store for tracking socket event performance.
 * Captures timing data for all socket events sent from the frontend.
 */

import { secureRandomId } from './secureRandom';

export interface ProfileEntry {
    _uid: string;       // Unique ID for React key (to avoid duplicate key warnings)
    requestId: string;
    eventName: string;
    tag?: string;       // Human-readable label (e.g., "Adding row", "Deleting row")
    startTime: number;
    endTime?: number;
    duration?: number;
    success: boolean;
    error?: string;
    timestamp: string;
    requestData?: any;  // The data sent in the request
    responseData?: any; // The data received in the response
}

class ProfilingStore {
    private entries: ProfileEntry[] = [];
    private maxEntries = 200;
    // Dev-only by default: each entry pins the FULL request + response payload
    // (node outputs can be MBs), so an always-on ring of 200 holds tens of MB
    // of the per-tab memory budget on every prod session. The DebugDrawer
    // flips it on when opened, so profiling starts at drawer-open in prod.
    private enabled = import.meta.env.DEV;

    /**
     * Record the start of a socket event
     */
    startEvent(requestId: string, eventName: string, requestData?: any, tag?: string): void {
        if (!this.enabled) return;

        // Filter out debug:get_logs to avoid pollution
        if (eventName === 'debug:get_logs') {
            console.log('[ProfilingStore] Skipping debug:get_logs');
            return;
        }

        // Check if this requestId is already being tracked (duplicate prevention)
        const existingEntry = this.entries.find(e => e.requestId === requestId && !e.endTime);
        if (existingEntry) {
            console.warn(`[ProfilingStore] Request ${requestId.slice(0, 8)}... already being tracked, skipping duplicate`);
            return;
        }

        // Generate unique ID for this entry (prevents React key collisions)
        const uniqueId = `${requestId}-${Date.now()}-${secureRandomId()}`;

        const entry: ProfileEntry = {
            _uid: uniqueId,
            requestId,
            eventName,
            tag,
            startTime: performance.now(),
            success: false,
            timestamp: new Date().toISOString(),
            requestData: requestData // Store the request data
        };

        this.entries.push(entry);
        const tagLabel = tag ? ` [${tag}]` : '';
        console.log(`[ProfilingStore] Started tracking: ${eventName}${tagLabel} (${requestId.slice(0, 8)}...) - Total entries: ${this.entries.length}`);

        // Keep only last N entries
        if (this.entries.length > this.maxEntries) {
            this.entries = this.entries.slice(-this.maxEntries);
        }
    }

    /**
     * Record the completion of a socket event
     */
    endEvent(requestId: string, success: boolean, error?: string, responseData?: any): void {
        if (!this.enabled) return;

        const entry = this.entries.find(e => e.requestId === requestId && !e.endTime);
        if (entry) {
            entry.endTime = performance.now();
            entry.duration = entry.endTime - entry.startTime;
            entry.success = success;
            entry.error = error;
            entry.responseData = responseData; // Store the response data
            console.log(`[ProfilingStore] Completed: ${entry.eventName} (${requestId.slice(0, 8)}...) - ${entry.duration.toFixed(2)}ms - ${success ? 'SUCCESS' : 'FAILED'}`);
        } else {
            console.warn(`[ProfilingStore] No pending entry found for requestId: ${requestId.slice(0, 8)}...`);
        }
    }

    /**
     * Get all profiling entries
     */
    getEntries(): ProfileEntry[] {
        return [...this.entries];
    }

    /**
     * Clear all profiling entries
     */
    clear(): void {
        this.entries = [];
    }

    /**
     * Enable/disable profiling
     */
    setEnabled(enabled: boolean): void {
        this.enabled = enabled;
    }

    /**
     * Check if profiling is enabled
     */
    isEnabled(): boolean {
        return this.enabled;
    }
}

// Global profiling store instance
export const profilingStore = new ProfilingStore();
