import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SevdeskIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/sevdesk.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const SevdeskNode: NodeDefinition = {
    type: 'automation-sevdesk', category: 'finance-accounting', label: 'Sevdesk',
    description: 'Trigger on new or updated contacts, invoices, orders and vouchers; manage Sevdesk accounting records',
    keywords: ['sevdesk', 'accounting', 'invoices', 'bookkeeping'],
    Icon: SevdeskIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SevdeskIcon} iconColor="" />),
};
