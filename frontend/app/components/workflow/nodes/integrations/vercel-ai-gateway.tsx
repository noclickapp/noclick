import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const VercelAiGatewayIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/vercel-ai-gateway.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const VercelAiGatewayNode: NodeDefinition = {
    type: 'automation-vercel-ai-gateway', category: 'ai', label: 'Vercel AI Gateway',
    description: 'Manage BYOK credentials, virtual models, routing rules and AI budgets',
    keywords: ['vercel', 'ai gateway', 'byok', 'budget', 'routing'],
    Icon: VercelAiGatewayIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={VercelAiGatewayIcon} iconColor="" />),
};
