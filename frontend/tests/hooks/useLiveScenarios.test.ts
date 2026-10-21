// @vitest-environment jsdom
//
// A rehearsable trigger wears its own name. Node definitions load per type, so the scenarios can arrive before the
// trigger's definition has: the name then comes from the catalog the dashboard already holds, never from the type
// string ("Cal Com" under an amber bolt read as unsupported).
import { renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('~/lib/socket-sender', async (importOriginal) => ({
    ...(await importOriginal<typeof import('~/lib/socket-sender')>()),
    sendEventAsync: vi.fn(async () => ({
        success: true,
        triggers: [{ node_type: 'automation-cal-com', operation: 'on_booking_created', situations: [] }],
    })),
}));

import { useLiveScenarios } from '~/components/design/rehearsal/useLiveScenarios';
import { getNodeDefinition } from '~/components/workflow/nodes/nodeDefinitions';
import { setNodeIconData } from '~/lib/nodeIconRegistry';

describe('useLiveScenarios', () => {
    it("names a trigger whose definition hasn't loaded by the catalog", async () => {
        setNodeIconData({
            'automation-cal-com': {
                type: 'automation-cal-com',
                label: 'Cal.com',
                description: '',
                iconColor: '',
                iconHtml: '',
                dimensions: { width: 90, height: 90, iconSize: 48 },
            },
        });
        expect(getNodeDefinition('automation-cal-com')).toBeUndefined();

        const { result } = renderHook(() => useLiveScenarios('wf-1'));
        await waitFor(() => expect(result.current.loading).toBe(false));
        expect(result.current.triggers.map((t) => t.nodeName)).toEqual(['Cal.com']);
    });
});
