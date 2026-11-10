import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const RegiondoIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/regiondo.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const RegiondoNode: NodeDefinition = {
    type: 'automation-regiondo', category: 'bookings', label: 'Regiondo',
    description: 'Sync bookings, customers and products; manage holds and cancel tickets',
    Icon: RegiondoIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={RegiondoIcon} iconColor="" />),
};
