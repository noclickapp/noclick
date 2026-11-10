import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const AirwallexIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/airwallex.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const AirwallexNode: NodeDefinition = {
    type: 'automation-airwallex', label: 'Airwallex',
    category: 'finance-accounting',
    description: 'React to deposits and transfer status changes; manage balances, beneficiaries and global accounts',
    Icon: AirwallexIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AirwallexIcon} iconColor="" />),
};
