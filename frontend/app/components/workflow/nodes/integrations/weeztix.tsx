import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const WeeztixIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/weeztix.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const WeeztixNode: NodeDefinition = {
    type: 'automation-weeztix', category: 'bookings', label: 'Weeztix',
    description: 'Manage event details, ticket types, shops and order receivers; read event and order data',
    keywords: ['Eventix', 'tickets', 'events', 'ticketing'],
    Icon: WeeztixIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={WeeztixIcon} iconColor="" />),
};
