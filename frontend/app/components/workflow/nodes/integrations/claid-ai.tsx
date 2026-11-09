import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ClaidAiIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/claid-ai.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const ClaidAiNode: NodeDefinition = {
    type: 'automation-claid-ai', category: 'ai', label: 'Claid Ai',
    description: 'Edit and generate images, create fashion models and videos, and manage storage connectors',
    keywords: ['claid_ai', 'background removal', 'upscale', 'product photography', 'virtual try on'],
    Icon: ClaidAiIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ClaidAiIcon} iconColor="" />),
};
