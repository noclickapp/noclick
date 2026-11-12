import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const QuipuIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/quipuapp.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);

export const QuipuNode: NodeDefinition = {
    type: 'automation-quipuapp', category: 'finance-accounting', label: 'Quipu',
    description: 'Manage contacts, invoices, simplified invoices, income and paysheets',
    keywords: ['accounting', 'invoicing', 'expenses', 'Quipuapp'],
    Icon: QuipuIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={QuipuIcon} iconColor="" />),
};
