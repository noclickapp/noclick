import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const GoTableIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/go-table.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const GoTableNode: NodeDefinition = {
    type: 'automation-go-table', category: 'bookings', label: 'Go Table',
    description: 'Manage restaurant reservations, guests and notes; read availability, offers, tables and reviews',
    keywords: ['GoTable', 'restaurant', 'reservations', 'guests'],
    Icon: GoTableIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={GoTableIcon} iconColor="" />),
};
