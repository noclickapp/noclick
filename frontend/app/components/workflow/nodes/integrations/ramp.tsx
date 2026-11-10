// Ramp cards, transactions, reimbursements and bills through the Developer API.
// The official Ramp mark identifies the service in the canvas and node picker.
import { memo, type CSSProperties } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const RampIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/ramp.svg" dark="/icons/ramp-dark.svg" className={className} style={{ ...style, objectFit: 'contain' }} />
);

export const RampNode: NodeDefinition = {
    type: 'automation-ramp',
    label: 'Ramp',
    description: 'Manage cards, transactions, reimbursements and bills in Ramp',
    category: 'finance-accounting',
    Icon: RampIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={RampIcon} iconColor="" />),
};
