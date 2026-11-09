import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const AutotaskIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/autotask.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain', backgroundColor: '#1a345a', borderRadius: 4, padding: 3 } as CSSProperties} />
);

export const AutotaskNode: NodeDefinition = {
    type: 'automation-autotask', category: 'support', label: 'Autotask',
    description: 'Manage tickets, companies, contacts, time entries and ticket notes',
    keywords: ['PSA', 'Datto', 'service desk', 'helpdesk', 'Kaseya'],
    Icon: AutotaskIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AutotaskIcon} iconColor="" />),
};
