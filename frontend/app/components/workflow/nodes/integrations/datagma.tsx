import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const DatagmaIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/datagma.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const DatagmaNode: NodeDefinition = {
    type: 'automation-datagma', category: 'crm-sales', label: 'Datagma',
    description: 'Find work emails and phone numbers, enrich people and companies, and detect job changes',
    keywords: ['lead enrichment', 'email finder', 'prospecting', 'contact data'],
    Icon: DatagmaIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={DatagmaIcon} iconColor="" />),
};
