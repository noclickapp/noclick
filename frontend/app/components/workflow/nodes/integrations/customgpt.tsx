import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const CustomgptIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/customgpt.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const CustomgptNode: NodeDefinition = {
    type: 'automation-customgpt', category: 'ai', label: 'CustomGPT.ai',
    description: 'Automate AI agents, conversations, documents and sources',
    Icon: CustomgptIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CustomgptIcon} iconColor="" />),
};
