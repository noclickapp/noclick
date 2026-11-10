import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const HumanitixIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/humanitix.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const HumanitixNode: NodeDefinition = {
    type: 'automation-humanitix', category: 'bookings', label: 'Humanitix',
    description: 'Start workflows from new or updated events, orders and tickets, and manage attendance',
    Icon: HumanitixIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={HumanitixIcon} iconColor="" />),
};
