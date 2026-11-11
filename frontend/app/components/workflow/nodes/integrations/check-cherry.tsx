// Check Cherry's self-registering node definition supplies its catalog and canvas identity.
// The operation and credential forms come from the generated backend schema.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const CheckCherryIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/check-cherry.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const CheckCherryNode: NodeDefinition = {
    type: 'automation-check-cherry', category: 'bookings', label: 'Check Cherry',
    description: 'Manage leads, bookings, proposals, appointments, payments and packages',
    keywords: ['CheckCherry', 'events', 'booking', 'CRM'],
    Icon: CheckCherryIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CheckCherryIcon} iconColor="" />),
};
