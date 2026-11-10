import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const FareHarborIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/fareharbor.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const FareHarborNode: NodeDefinition = {
    type: 'automation-fareharbor', category: 'bookings', label: 'FareHarbor',
    description: 'Manage tour bookings, availability, check-ins and crew assignments',
    Icon: FareHarborIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={FareHarborIcon} iconColor="" />),
};
