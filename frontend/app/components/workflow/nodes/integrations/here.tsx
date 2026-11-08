import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const HereIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/here.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const HereNode: NodeDefinition = {
    type: 'automation-here', category: 'industry', label: 'HERE',
    description: 'Track devices, read telemetry, and manage geofences, locations, rules and device metadata',
    keywords: ['here', 'tracking', 'location', 'IoT', 'geofence', 'fleet', 'logistics'],
    Icon: HereIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={HereIcon} iconColor="" />),
};
