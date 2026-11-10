import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ZepIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/zep.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const ZepNode: NodeDefinition = {
    type: 'automation-zep', category: 'ai', label: 'Zep',
    description: 'Manage users, conversation memory, messages and context graphs',
    Icon: ZepIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ZepIcon} iconColor="" />),
};
