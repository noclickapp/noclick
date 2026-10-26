// The reminders the coordinator set (schedule_alarm), read back by id with coordinator:alarms so each card says
// whether its reminder is still to come, went off, or was called off, after a reload too. Read with the thread and
// again with each new message: a reminder that goes off answers in the thread.
import { createContext, useContext, useMemo } from 'react';
import { READ_TIMEOUT_MS, useReadBack } from '~/hooks/useReadBack';
import type { JsonObject } from '~/lib/coordinatorToolCalls';
import { sendEventAsync } from '~/lib/socket-sender';
import { CoordinatorAlarmsRequest } from '~/types/socket-events.generated';

export interface CoordinatorAlarm extends JsonObject {
    schedule_id: string;
    /** `scheduled` while it's still to come; else how its last time went (`success`, `failed`) or `cancelled`. */
    status: string;
    /** When it last went off. */
    fired_at?: string;
}

export interface CoordinatorAlarms {
    /** Whether this server reads reminders back at all. */
    live: boolean;
    get(scheduleId: string | undefined): CoordinatorAlarm | undefined;
}

export const CoordinatorAlarmsContext = createContext<CoordinatorAlarms>({
    live: false,
    get: () => undefined,
});

export function useCoordinatorAlarm(scheduleId: string | undefined): {
    live: boolean;
    alarm: CoordinatorAlarm | undefined;
} {
    const alarms = useContext(CoordinatorAlarmsContext);
    return { live: alarms.live, alarm: alarms.get(scheduleId) };
}

async function readAlarms(
    ids: [string, ...string[]]
): Promise<CoordinatorAlarm[]> {
    const reply = (await sendEventAsync(
        CoordinatorAlarmsRequest.create({
            request_id: crypto.randomUUID(),
            schedule_ids: ids,
        }),
        undefined,
        READ_TIMEOUT_MS
    )) as {
        alarms?: CoordinatorAlarm[];
        error?: string;
    };
    if (reply.error || !reply.alarms)
        throw new Error(reply.error || 'No alarms in the reply');
    return reply.alarms;
}

const alarmIdOf = (alarm: CoordinatorAlarm) => alarm.schedule_id;

/** Reads `scheduleIds` back, again whenever `nudge` changes (a new message). */
export function useCoordinatorAlarms(
    scheduleIds: readonly string[],
    nudge: unknown
): CoordinatorAlarms {
    const { live, byId } = useReadBack(
        scheduleIds,
        nudge,
        readAlarms,
        alarmIdOf
    );
    return useMemo(
        () => ({ live, get: (id) => (id ? byId[id] : undefined) }),
        [live, byId]
    );
}
