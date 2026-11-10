import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const KiwifyIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/kiwify.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const KiwifyNode: NodeDefinition = {
    type: 'automation-kiwify', category: 'ecommerce', label: 'Kiwify',
    description: 'Automate sales, refunds, products, affiliates, webhooks and installment plans',
    Icon: KiwifyIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={KiwifyIcon} iconColor="" />),
};
