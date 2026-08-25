// Cron trigger node definition.
// This node acts as an entry point for workflows triggered by a cron schedule.
// Uses external relay services for reliable, scalable scheduling.

import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import { Clock } from 'lucide-react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const DAYS_OF_WEEK = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

function toNum(value: unknown, fallback: number): number {
    return typeof value === 'number' ? value : Number(value) || fallback;
}

function ordinal(n: number): string {
    if (n > 3 && n < 21) return 'th';
    switch (n % 10) {
        case 1: return 'st';
        case 2: return 'nd';
        case 3: return 'rd';
        default: return 'th';
    }
}

function fmtTime(hour: number, minute: number): string {
    const h12 = hour === 0 ? 12 : hour > 12 ? hour - 12 : hour;
    return `${h12}:${String(minute).padStart(2, '0')} ${hour < 12 ? 'AM' : 'PM'}`;
}

// Compact single-entry summary for the card pill — a terser counterpart to
// ScheduleWidget's full "Runs daily at 9:00 AM" sentence shown in the config panel.
function summarizeEntry(s: Record<string, unknown>): string {
    switch (s.frequency) {
        case 'seconds': return `every ${toNum(s.interval, 1)}s`;
        case 'minutes': return `every ${toNum(s.interval, 1)}m`;
        case 'hours': return `every ${toNum(s.interval, 1)}h`;
        case 'day': return `${fmtTime(toNum(s.hour, 9), toNum(s.minute, 0))} daily`;
        case 'week': return `${DAYS_OF_WEEK[toNum(s.dayOfWeek, 1)] ?? 'Mon'} ${fmtTime(toNum(s.hour, 9), toNum(s.minute, 0))}`;
        case 'weeks': return `${toNum(s.interval, 2)}w · ${DAYS_OF_WEEK[toNum(s.dayOfWeek, 1)] ?? 'Mon'}`;
        case 'month': { const d = toNum(s.dayOfMonth, 1); return `${d}${ordinal(d)} ${fmtTime(toNum(s.hour, 9), toNum(s.minute, 0))}`; }
        default: return '';
    }
}

// Build the card caption from the node's schedules config. Returns undefined
// when no concrete schedule is set so the card stays icon-only rather than
// showing a misleading placeholder.
export function getScheduleCaption(config?: Record<string, unknown>): string | undefined {
    const raw = config?.schedules;
    const schedules: unknown[] = Array.isArray(raw) ? raw : [];
    const first = schedules.find((s): s is Record<string, unknown> => !!s && typeof s === 'object');
    if (!first) return undefined;
    const base = summarizeEntry(first);
    if (!base) return undefined;
    return schedules.length > 1 ? `${base} +${schedules.length - 1}` : base;
}

const CronTriggerNodeComponent = (props: NodeProps) => {
    const config = (props.data as { config?: Record<string, unknown> } | undefined)?.config;
    return <AutomationNode {...props} Icon={Clock} iconColor="text-foreground" caption={getScheduleCaption(config)} />;
};

export const CronTriggerNode: NodeDefinition = {
    type: 'trigger-cron',
    label: 'Schedule',
    description: 'Cron Schedule',
    keywords: ['schedule', 'scheduled', 'cron', 'timer', 'recurring', 'periodic', 'repeat', 'interval', 'every day', 'daily', 'hourly', 'weekly', 'monthly', 'time of day', 'clock', 'automatic run'],
    Icon: Clock,
    iconColor: 'text-foreground',
    dimensions: DIMENSIONS,
    component: memo(CronTriggerNodeComponent),
};
