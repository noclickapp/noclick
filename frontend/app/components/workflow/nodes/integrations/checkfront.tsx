// Register Checkfront in the workflow canvas and integration catalog.
// Operation forms and manual credentials come from its generated backend schema.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const CheckfrontIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/checkfront.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const CheckfrontNode: NodeDefinition = {
    type: 'automation-checkfront', category: 'bookings', label: 'Checkfront',
    description: 'Manage bookings, customers, notes and guest check-in; read products and transactions',
    Icon: CheckfrontIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CheckfrontIcon} iconColor="" />),
};
