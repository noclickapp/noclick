// The rehearsal surfaces' provider-mark map: every registry node's icon keyed
// by the backend tool-name slug (`automation-slack` → `slack`), so tool rows,
// staged cards and outcome frames resolve real brand marks. Extracted from
// AgentChatBlock so the Setup tab's staged preview shares the same map.

import { useMemo } from 'react';
import type { ReactNode } from 'react';
import { AVAILABLE_NODES } from '~/components/workflow/nodes/nodeRegistry';

export function useRehearsalIcons(): Record<string, { node: ReactNode }> {
    return useMemo(() => {
        const icons: Record<string, { node: ReactNode }> = {};
        for (const def of AVAILABLE_NODES) {
            const Icon = def.Icon;
            if (!Icon) continue;
            const slug = def.type.replace(/^automation-/, '').replace(/-/g, '_');
            icons[slug] = {
                node: <Icon className="h-full w-full" style={{ color: def.iconColor }} />,
            };
        }
        return icons;
    }, []);
}
