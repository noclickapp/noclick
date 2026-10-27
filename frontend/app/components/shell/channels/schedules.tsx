// When a channel posts on its own: each schedule in words ("Every Monday at 8:00 AM"), on the header beside its name
// and in full at the start of the channel with what it posts. Its clock is named only when it isn't yours.
import { CalendarClock } from 'lucide-react';
import { Tooltip, TooltipContent, TooltipTrigger } from '~/components/ui/tooltip';
import { describeCronIn } from '~/utils/scheduleFormat';
import type { ChannelSchedule } from './types';

/** A schedule in words; its cron expression when it's more than words say simply. */
export function scheduleSentence(schedule: ChannelSchedule): string {
    return describeCronIn(schedule.cron, schedule.tz) ?? `${schedule.cron} (${schedule.tz ?? 'UTC'})`;
}

function nextLabel(schedule: ChannelSchedule): string | null {
    const next = Date.parse(schedule.nextRun ?? '');
    return Number.isFinite(next) ? `Next ${new Date(next).toLocaleDateString(undefined, { weekday: 'long', month: 'short', day: 'numeric' })}` : null;
}

/** The header's: the first schedule, the rest counted; what it posts and when next on hover. */
export function ScheduleChip({ schedules }: { schedules: ChannelSchedule[] }) {
    const [first] = schedules;
    const next = nextLabel(first);
    return (
        <Tooltip>
            <TooltipTrigger asChild>
                <span className="inline-flex shrink-0 items-center gap-1.5 text-[13px] text-foreground/75" data-testid="channel-schedule">
                    <CalendarClock className="h-3.5 w-3.5 text-muted-foreground" strokeWidth={1.75} />
                    {scheduleSentence(first)}
                    {schedules.length > 1 && <span className="text-muted-foreground">+{schedules.length - 1}</span>}
                </span>
            </TooltipTrigger>
            <TooltipContent side="bottom" sideOffset={6} className="max-w-[320px] rounded-lg px-2.5 py-1.5 text-[12.5px] leading-snug">
                {next && <p className="font-medium">{next}</p>}
                <p className="line-clamp-3 text-muted-foreground">Posts “{first.message}”</p>
            </TooltipContent>
        </Tooltip>
    );
}

/** At the start of the channel: each schedule, and what it posts. */
export function ScheduleLines({ schedules }: { schedules: ChannelSchedule[] }) {
    return (
        <>
            {schedules.map((s) => (
                <p key={s.id} className="mt-2 flex min-w-0 items-center gap-2.5 text-[13px] text-muted-foreground" data-testid="channel-schedule-line">
                    <span className="grid w-5 shrink-0 place-items-center">
                        <CalendarClock className="h-4 w-4" strokeWidth={1.75} />
                    </span>
                    <span className="shrink-0 text-foreground/80">{scheduleSentence(s)}</span>
                    {s.message && <span className="min-w-0 truncate">posts “{s.message}”</span>}
                </p>
            ))}
        </>
    );
}
