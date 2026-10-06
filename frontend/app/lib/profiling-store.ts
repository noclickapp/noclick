/**
 * Profiling store for tracking socket event performance.
 * Captures timing data for all socket events sent from the frontend.
 */

import { secureRandomId } from './secureRandom';
import { diagnosticSocketText, projectSocketDiagnostics } from './socket-diagnostics';

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
    requestData?: unknown;  // Diagnostic projection of the request
    responseData?: unknown; // Diagnostic projection of the response
}

class ProfilingStore {
    private entries: ProfileEntry[] = [];
    private maxEntries = 200;
    // The drawer enables profiling in production; retained payloads are bounded diagnostic copies.
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
            tag: diagnosticSocketText(eventName, tag),
            startTime: performance.now(),
            success: false,
            timestamp: new Date().toISOString(),
            requestData: projectSocketDiagnostics(eventName, requestData)
        };

        this.entries.push(entry);
        const tagLabel = entry.tag ? ` [${entry.tag}]` : '';
        console.log(`[ProfilingStore] Started tracking: ${eventName}${tagLabel} (${requestId.slice(0, 8)}...) - Total entries: ${this.entries.length}`);

        // Keep only last N entries
        if (this.entries.length > this.maxEntries) {
            this.entries = this.entries.slice(-this.maxEntries);
        }
    }

    /**
     * Record the completion of a socket event
     */
    endEvent(requestId: string, success: boolean, error?: unknown, responseData?: unknown): void {
        if (!this.enabled) return;

        const entry = this.entries.find(e => e.requestId === requestId && !e.endTime);
        if (entry) {
            entry.endTime = performance.now();
            entry.duration = entry.endTime - entry.startTime;
            entry.success = success;
            entry.error = diagnosticSocketText(entry.eventName, error);
            entry.responseData = projectSocketDiagnostics(entry.eventName, responseData);
            console.log(`[ProfilingStore] Completed: ${entry.eventName} (${requestId.slice(0, 8)}...) - ${entry.duration.toFixed(2)}ms - ${success ? 'SUCCESS' : 'FAILED'}`);
        } else {
            console.warn(`[ProfilingStore] No pending entry found for requestId: ${requestId.slice(0, 8)}...`);
        }
    }

    /**
     * Get all profiling entries
     */
    getEntries(): ProfileEntry[] {
        // Re-project older in-memory entries and prevent consumers retaining mutable payload references.
        return this.entries.map(entry => ({
            ...entry,
            tag: diagnosticSocketText(entry.eventName, entry.tag),
            error: diagnosticSocketText(entry.eventName, entry.error),
            requestData: projectSocketDiagnostics(entry.eventName, entry.requestData),
            responseData: projectSocketDiagnostics(entry.eventName, entry.responseData),
        }));
    }

    getEventName(requestId: string): string | undefined {
        return this.entries.find(entry => entry.requestId === requestId && !entry.endTime)?.eventName;
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
