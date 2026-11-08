import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const FleetioIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/fleetio.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const FleetioNode: NodeDefinition = {
    type: 'automation-fleetio', category: 'industry', label: 'Fleetio',
    description: 'Manage fleet vehicles, contacts, vendors and maintenance issues',
    Icon: FleetioIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={FleetioIcon} iconColor="" />),
};
