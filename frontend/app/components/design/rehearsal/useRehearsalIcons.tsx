// The rehearsal surfaces' provider-mark map: each loaded node definition's icon keyed
// by the backend tool-name slug (`automation-slack` → `slack`), so tool rows, staged
// cards and outcome frames resolve real brand marks. The rehearsed workflow's nodes are
// on its canvas, so their definitions have loaded; the map grows as more land.
// Extracted from AgentChatBlock so the Setup tab's staged preview shares the same map.

import { useMemo, useSyncExternalStore } from 'react';
import type { ReactNode } from 'react';
import { nodeDefinitionStore } from '~/components/workflow/nodes/nodeDefinitions';

export function useRehearsalIcons(): Record<string, { node: ReactNode }> {
    const version = useSyncExternalStore(nodeDefinitionStore.subscribe, nodeDefinitionStore.version, () => -1);
    return useMemo(() => {
        const icons: Record<string, { node: ReactNode }> = {};
        for (const def of Object.values(nodeDefinitionStore.values)) {
            const Icon = def.Icon;
            if (!Icon) continue;
            const slug = def.type.replace(/^automation-/, '').replace(/-/g, '_');
            icons[slug] = {
                node: <Icon className="h-full w-full" style={{ color: def.iconColor }} />,
            };
        }
        return icons;
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [version]);
}
