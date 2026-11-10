import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const AiMlApiIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <>
        <img src="/icons/ai-ml-api.svg" alt="" aria-hidden="true" className={`${className ?? ''} dark:hidden`}
            style={{ ...style, objectFit: 'contain' }} />
        <img src="/icons/ai-ml-api-dark.svg" alt="" aria-hidden="true" className={`${className ?? ''} hidden dark:block`}
            style={{ ...style, objectFit: 'contain' }} />
    </>
);

export const AiMlApiNode: NodeDefinition = {
    type: 'automation-ai-ml-api', category: 'ai', label: 'AI/ML API',
    description: 'Generate text, images, audio and video, create embeddings, transcribe audio and extract documents',
    Icon: AiMlApiIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AiMlApiIcon} iconColor="" />),
};
