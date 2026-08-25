// Global store for tracking SDK bridge calls from custom component iframes.
// Used by the /sdk_debug drawer to display call timing, results, and errors.

import { secureRandomId } from './secureRandom';

export interface SDKCallEntry {
  _uid: string;
  requestId: string;
  method: string;
  params: Record<string, unknown>;
  nodeId: string;
  startTime: number;
  endTime?: number;
  duration?: number;
  status: 'pending' | 'success' | 'error' | 'streaming';
  result?: unknown;
  error?: string;
  timestamp: string;
  streamEvents?: Array<{ event: string; nodeId?: string; data?: unknown; time: number }>;
}

type ChangeListener = () => void;

class SDKDebugStore {
  private entries: SDKCallEntry[] = [];
  private maxEntries = 300;
  private listeners: Set<ChangeListener> = new Set();

  startCall(requestId: string, method: string, params: Record<string, unknown>, nodeId: string): void {
    const entry: SDKCallEntry = {
      _uid: `${requestId}-${Date.now()}-${secureRandomId()}`,
      requestId,
      method,
      params,
      nodeId,
      startTime: performance.now(),
      status: 'pending',
      timestamp: new Date().toISOString(),
    };
    this.entries.push(entry);
    if (this.entries.length > this.maxEntries) {
      this.entries = this.entries.slice(-this.maxEntries);
    }
    this.notifyListeners();
  }

  endCall(requestId: string, result: unknown): void {
    const entry = this.entries.find(e => e.requestId === requestId && e.status === 'pending');
    if (!entry) return;
    entry.endTime = performance.now();
    entry.duration = entry.endTime - entry.startTime;
    entry.status = 'success';
    entry.result = result;
    this.notifyListeners();
  }

  errorCall(requestId: string, error: string): void {
    const entry = this.entries.find(e => e.requestId === requestId && (e.status === 'pending' || e.status === 'streaming'));
    if (!entry) return;
    entry.endTime = performance.now();
    entry.duration = entry.endTime - entry.startTime;
    entry.status = 'error';
    entry.error = error;
    this.notifyListeners();
  }

  markStreaming(requestId: string): void {
    const entry = this.entries.find(e => e.requestId === requestId && e.status === 'pending');
    if (!entry) return;
    entry.status = 'streaming';
    entry.streamEvents = [];
    this.notifyListeners();
  }

  addStreamEvent(requestId: string, event: string, nodeId?: string, data?: unknown): void {
    const entry = this.entries.find(e => e.requestId === requestId && e.status === 'streaming');
    if (!entry) return;
    if (!entry.streamEvents) entry.streamEvents = [];
    entry.streamEvents.push({ event, nodeId, data, time: performance.now() - entry.startTime });
    if (event === 'done') {
      entry.endTime = performance.now();
      entry.duration = entry.endTime - entry.startTime;
      entry.status = 'success';
    }
    this.notifyListeners();
  }

  getEntries(): SDKCallEntry[] {
    return [...this.entries];
  }

  clear(): void {
    this.entries = [];
    this.notifyListeners();
  }

  subscribe(listener: ChangeListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private notifyListeners(): void {
    this.listeners.forEach(fn => fn());
  }
}

export const sdkDebugStore = new SDKDebugStore();
