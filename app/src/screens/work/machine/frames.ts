// A machine's frames, wherever its dialog opens: Work hands them over its live context, and each one for the machine
// reads it again. Add your computer and buying a machine both watch the one they made come online this way.
import { useContext, useEffect } from 'react';
import { invalidateV1 } from '@/sdk/useV1';
import { WorkLiveContext } from '@/sdk/live';

/** Reads `key` again on each frame for machine `id`; the app's Resources reads it again through the console's own
 *  (`machines/<id>` is one of a machine frame's stale reads). */
export function useMachineFrames(id: string | null, key: string | null) {
    const live = useContext(WorkLiveContext);
    useEffect(() => {
        if (!live || !id || !key) return;
        return live.on('platform:resource', (frame) => {
            if (frame.kind === 'machine' && frame.id === id) invalidateV1(key);
        });
    }, [live, id, key]);
}
