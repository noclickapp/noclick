import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const Dpd2Icon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/dpd2.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const Dpd2Node: NodeDefinition = {
    type: 'automation-dpd2', category: 'ecommerce', label: 'Dpd2',
    description: 'Read storefronts, products, purchases, customers and subscribers; resend purchases',
    Icon: Dpd2Icon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={Dpd2Icon} iconColor="" />),
};
