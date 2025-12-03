/**
 * Time utility functions for debug views.
 * Converts timestamps to IST (Indian Standard Time).
 */

/**
 * Convert ISO timestamp or Date to IST time string
 * @param timestamp ISO string or Date object
 * @returns Formatted time string in IST (HH:MM:SS format)
 */
export function toISTTime(timestamp: string | Date): string {
    const date = typeof timestamp === 'string' ? new Date(timestamp) : timestamp;

    // Convert to IST (UTC+5:30)
    const istDate = new Date(date.toLocaleString('en-US', { timeZone: 'Asia/Kolkata' }));

    return istDate.toLocaleTimeString('en-IN', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false
    });
}

/**
 * Get end timestamp for a profiling entry
 * @param startTimestamp ISO start timestamp
 * @param durationMs Duration in milliseconds
 * @returns ISO timestamp string for end time
 */
export function getEndTimestamp(startTimestamp: string, durationMs: number): string {
    const startTime = new Date(startTimestamp).getTime();
    const endTime = startTime + durationMs;
    return new Date(endTime).toISOString();
}
