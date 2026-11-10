import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SendfoxIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/sendfox.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const SendfoxNode: NodeDefinition = {
    type: 'automation-sendfox', category: 'marketing', label: 'Sendfox',
    description: 'Manage SendFox contacts, lists and tags; read campaigns and statistics',
    Icon: SendfoxIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SendfoxIcon} iconColor="" />),
};
