/**
 * AlarmViewerWidget - Displays active alarms for an alarm node with search/filter.
 * Fetches alarm data via the load_field_value socket event and renders a filterable list.
 */

import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, Search, Bell, Clock, Repeat, X } from 'lucide-react';
import { sendEventAsync } from '~/lib/socket-sender';
import { fuzzyFilter } from '~/utils/fuzzySearch';

interface Alarm {
    schedule_id: string;
    type: 'one-time' | 'cron';
    enabled: boolean;
    next_run: string | null;
    created_at: string | null;
    message: string;
    conversation_key: string | null;
}

interface AlarmViewerWidgetProps {
    nodeId: string;
    nodeType: string;
    workflowId: string;
}

export function AlarmViewerWidget({ nodeId, nodeType, workflowId }: AlarmViewerWidgetProps) {
    const [alarms, setAlarms] = useState<Alarm[]>([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [searchQuery, setSearchQuery] = useState('');

    const fetchAlarms = useCallback(async () => {
        if (!workflowId || !nodeId) return;

        setLoading(true);
        setError(null);

        try {
            const response = await sendEventAsync({
                event_name: 'workflow:node:load_value',
                node_type: nodeType,
                field_name: 'active_alarms',
                workflow_id: workflowId,
                node_id: nodeId,
                context: {},
            }) as { success: boolean; value?: { alarms: Alarm[]; count: number; error?: string }; message?: string };

            if (response?.success && response.value) {
                if (response.value.error) {
                    setError(response.value.error);
                } else {
                    setAlarms(response.value.alarms || []);
                }
            } else {
                setError(response?.message || 'Failed to load alarms');
            }
        } catch (e) {
            setError('Connection error');
        } finally {
            setLoading(false);
        }
    }, [workflowId, nodeId, nodeType]);

    useEffect(() => {
        fetchAlarms();
    }, [fetchAlarms]);

    // Client-side filter across all visible fields
    const filteredAlarms = fuzzyFilter(alarms, searchQuery, a => [
        { text: (a.message || '').toLowerCase(), weight: 1, fuzzy: true },
        { text: (a.conversation_key || '').toLowerCase(), weight: 0.6, fuzzy: true },
        { text: (a.schedule_id || '').toLowerCase(), weight: 0.6, fuzzy: true },
    ]);

    const formatTime = (iso: string | null) => {
        if (!iso) return '—';
        try {
            const d = new Date(iso);
            return d.toLocaleString(undefined, {
                month: 'short', day: 'numeric',
                hour: '2-digit', minute: '2-digit',
            });
        } catch {
            return iso;
        }
    };

    return (
        <div className="space-y-2">
            {/* Search + Refresh bar */}
            <div className="flex items-center gap-1.5">
                <div className="relative flex-1">
                    <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground dark:text-zinc-500" />
                    <input
                        type="text"
                        value={searchQuery}
                        onChange={e => setSearchQuery(e.target.value)}
                        placeholder="Filter by message, key, or ID..."
                        className="w-full pl-8 pr-7 py-1.5 text-xs rounded-md border border-border dark:border-white/[0.08] bg-foreground/[0.03] text-foreground outline-none placeholder:text-[hsl(var(--placeholder))] focus:border-foreground/20"
                    />
                    {searchQuery && (
                        <button
                            onClick={() => setSearchQuery('')}
                            className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground dark:text-zinc-500 hover:text-foreground/80"
                        >
                            <X className="w-3 h-3" />
                        </button>
                    )}
                </div>
                <button
                    onClick={fetchAlarms}
                    disabled={loading}
                    className="p-1.5 rounded-md border border-border dark:border-white/[0.08] bg-foreground/[0.03] text-muted-foreground hover:text-foreground hover:bg-foreground/[0.06] transition-colors disabled:opacity-50"
                    title="Refresh"
                >
                    <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
                </button>
            </div>

            {/* Error state */}
            {error && (
                <div className="px-3 py-2 text-xs text-red-600 dark:text-red-400 bg-red-500/10 rounded-md border border-red-500/20">
                    {error}
                </div>
            )}

            {/* Alarm list */}
            {!error && filteredAlarms.length === 0 && !loading && (
                <div className="px-3 py-4 text-center text-xs text-muted-foreground dark:text-zinc-500">
                    <Bell className="w-4 h-4 mx-auto mb-1.5 opacity-50" />
                    {alarms.length === 0 ? 'No active alarms' : 'No alarms match filter'}
                </div>
            )}

            {filteredAlarms.length > 0 && (
                <div className="space-y-1">
                    <div className="text-[10px] text-muted-foreground dark:text-zinc-500 uppercase tracking-wider px-1">
                        {filteredAlarms.length} alarm{filteredAlarms.length !== 1 ? 's' : ''}
                    </div>
                    {filteredAlarms.map(alarm => (
                        <div
                            key={alarm.schedule_id}
                            className={`px-2.5 py-2 rounded-md border text-xs space-y-1 ${
                                alarm.enabled
                                    ? 'border-border dark:border-white/[0.08] bg-foreground/[0.02]'
                                    : 'border-border dark:border-white/[0.05] bg-foreground/[0.01] opacity-60'
                            }`}
                        >
                            {/* Top row: type badge + message */}
                            <div className="flex items-start gap-1.5">
                                <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium shrink-0 ${
                                    alarm.type === 'one-time'
                                        ? 'bg-blue-500/15 text-blue-600 dark:text-blue-400'
                                        : 'bg-purple-500/15 text-purple-600 dark:text-purple-400'
                                }`}>
                                    {alarm.type === 'one-time'
                                        ? <Clock className="w-2.5 h-2.5" />
                                        : <Repeat className="w-2.5 h-2.5" />
                                    }
                                    {alarm.type === 'one-time' ? 'Once' : 'Cron'}
                                </span>
                                <span className="text-foreground/80 break-words leading-relaxed">
                                    {alarm.message || <span className="text-muted-foreground/70 dark:text-zinc-600 italic">No message</span>}
                                </span>
                            </div>
                            {/* Bottom row: metadata */}
                            <div className="flex items-center gap-3 text-[10px] text-muted-foreground dark:text-zinc-500">
                                {alarm.next_run && (
                                    <span title="Next run">Next: {formatTime(alarm.next_run)}</span>
                                )}
                                {alarm.conversation_key && (
                                    <span title="Conversation key" className="truncate max-w-[120px]">
                                        Key: {alarm.conversation_key}
                                    </span>
                                )}
                                {!alarm.enabled && (
                                    <span className="text-yellow-500">Disabled</span>
                                )}
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {/* Loading skeleton */}
            {loading && alarms.length === 0 && (
                <div className="space-y-1.5">
                    {[1, 2].map(i => (
                        <div key={i} className="h-14 rounded-md bg-foreground/[0.03] animate-pulse" />
                    ))}
                </div>
            )}
        </div>
    );
}
