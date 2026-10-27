// The schedules that post in an open channel, read when it opens and again when the channel itself changes (a
// `channel` change through the transport). Empty until read; a read that fails leaves them unsaid rather than wrong.
import { useEffect, useState } from 'react';
import type { ChannelsTransport } from '~/components/shell/channels/platform';
import type { ChannelSchedule } from '~/components/shell/channels/types';

export function useChannelSchedules(transport: ChannelsTransport, channelId: string | null): ChannelSchedule[] {
    const [read, setRead] = useState<{ channelId: string; schedules: ChannelSchedule[] } | null>(null);
    useEffect(() => {
        if (!channelId) return;
        let live = true;
        const load = () =>
            transport.schedules(channelId).then(
                (schedules) => live && setRead({ channelId, schedules }),
                (error) => console.warn('[channels] reading the schedules failed:', error)
            );
        void load();
        const stop = transport.subscribe((change) => {
            if (change.kind === 'channel' && (!change.channelId || change.channelId === channelId)) void load();
        });
        return () => {
            live = false;
            stop();
        };
    }, [transport, channelId]);
    return read && read.channelId === channelId ? read.schedules : [];
}
