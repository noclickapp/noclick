// Adds NeetoCal to the workflow canvas and integration catalog.
// Uses the official provider icon and the bookings category for discovery.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const NeetoCalIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/neetocal.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const NeetoCalNode: NodeDefinition = {
    type: 'automation-neetocal', category: 'bookings', label: 'NeetoCal',
    description: 'Automate bookings, scheduling links and availability; watch booking changes',
    Icon: NeetoCalIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={NeetoCalIcon} iconColor="" />),
};
