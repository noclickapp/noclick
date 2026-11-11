// ZonnaGPS exposes fleet actions and signed event triggers in the workflow catalog.
// Its provider-owned app mark has separate light and dark variants for readable tiles.
import { memo, type CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ZonnaGPSIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <>
        <img src="/icons/zonnagps.svg" alt="" aria-hidden="true" className={`${className ?? ''} dark:hidden`} style={style} />
        <img src="/icons/zonnagps-dark.svg" alt="" aria-hidden="true" className={`${className ?? ''} hidden dark:block`} style={style} />
    </>
);

export const ZonnaGPSNode: NodeDefinition = {
    type: 'automation-zonnagps', category: 'industry', label: 'ZonnaGPS',
    description: 'Manage fleet vehicles, drivers, places, geofences, reports and signed fleet events',
    keywords: ['GPS', 'fleet', 'tracking', 'vehicles', 'geofence'],
    Icon: ZonnaGPSIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ZonnaGPSIcon} iconColor="" />),
};
