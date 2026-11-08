import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const BonsaiIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/bonsai.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const BonsaiNode: NodeDefinition = {
    type: 'automation-bonsai', category: 'crm-sales', label: 'Bonsai',
    description: 'Manage companies, contacts, deals, projects, tasks, time entries and invoices',
    Icon: BonsaiIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BonsaiIcon} iconColor="" />),
};
