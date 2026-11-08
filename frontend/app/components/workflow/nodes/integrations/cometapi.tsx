import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const CometAPIIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/cometapi.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const CometAPINode: NodeDefinition = {
    type: 'automation-cometapi',
    category: 'ai',
    label: 'CometAPI',
    description: 'Generate text, embeddings, images and videos, check tasks and key usage',
    keywords: ['comet', 'cometapi', 'chat', 'claude', 'flux', 'midjourney', 'runway'],
    Icon: CometAPIIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CometAPIIcon} iconColor="" />),
};
