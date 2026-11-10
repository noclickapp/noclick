import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SymplaIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/sympla.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const SymplaNode: NodeDefinition = {
    type: 'automation-sympla', category: 'bookings', label: 'Sympla',
    description: 'Watch new or updated orders and participants, read events, and check in tickets',
    Icon: SymplaIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SymplaIcon} iconColor="" />),
};
