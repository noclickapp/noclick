import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SierraInteractiveIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/sierra-interactive.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const SierraInteractiveNode: NodeDefinition = {
    type: 'automation-sierra-interactive', category: 'crm-sales', label: 'Sierra Interactive',
    description: 'Manage real estate leads, tasks, notes, saved listings, inquiries and action plans',
    keywords: ['real estate', 'CRM', 'leads'],
    Icon: SierraInteractiveIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SierraInteractiveIcon} iconColor="" />),
};
