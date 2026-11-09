import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ActionstepIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/actionstep.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const ActionstepNode: NodeDefinition = {
    type: 'automation-actionstep', category: 'industry', label: 'Actionstep',
    description: 'Manage legal matters, contacts, tasks and file notes; read time entries',
    Icon: ActionstepIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ActionstepIcon} iconColor="" />),
};
