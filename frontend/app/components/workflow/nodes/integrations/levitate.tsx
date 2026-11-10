import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const LevitateIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/levitate.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const LevitateNode: NodeDefinition = {
    type: 'automation-levitate', category: 'crm-sales', label: 'Levitate',
    description: 'Manage contacts, companies, key facts and notes',
    Icon: LevitateIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={LevitateIcon} iconColor="" />),
};
