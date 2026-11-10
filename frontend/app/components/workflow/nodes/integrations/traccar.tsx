import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const TraccarIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/traccar.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const TraccarNode: NodeDefinition = {
    type: 'automation-traccar', category: 'industry', label: 'Traccar',
    description: 'Automate fleet devices, geofences, commands and reports; monitor device events',
    Icon: TraccarIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TraccarIcon} iconColor="" />),
};
