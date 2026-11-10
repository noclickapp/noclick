import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const VercelAiGatewayIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/vercel-ai-gateway.svg" dark="/icons/vercel-ai-gateway-dark.svg" className={className} style={style} />
);

export const VercelAiGatewayNode: NodeDefinition = {
    type: 'automation-vercel-ai-gateway', category: 'ai', label: 'Vercel AI Gateway',
    description: 'Manage BYOK credentials, virtual models, routing rules and AI budgets',
    keywords: ['vercel', 'ai gateway', 'byok', 'budget', 'routing'],
    Icon: VercelAiGatewayIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={VercelAiGatewayIcon} iconColor="" />),
};
