import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const CliengoIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/cliengo.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const CliengoNode: NodeDefinition = {
    type: 'automation-cliengo', category: 'crm-sales', label: 'Cliengo',
    description: 'Manage contacts, conversations, messages, tags and sales phases',
    Icon: CliengoIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CliengoIcon} iconColor="" />),
};
