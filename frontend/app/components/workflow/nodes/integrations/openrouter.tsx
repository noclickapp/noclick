import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const OpenRouterIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/openrouter.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const OpenRouterNode: NodeDefinition = {
    type: 'automation-openrouter', label: 'OpenRouter',
    description: 'Generate chat and embeddings, discover models, monitor usage and manage API keys',
    Icon: OpenRouterIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OpenRouterIcon} iconColor="" />),
};
