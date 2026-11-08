import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ApipieAIIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/apipie-ai.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const ApipieAINode: NodeDefinition = {
    type: 'automation-apipie-ai', category: 'ai', label: 'APIpie AI',
    description: 'Generate AI content and manage vectors, RAG documents and app state',
    Icon: ApipieAIIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ApipieAIIcon} iconColor="" />),
};
