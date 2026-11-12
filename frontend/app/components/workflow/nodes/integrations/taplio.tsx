// Adds Taplio to the workflow canvas and integration catalog.
// Uses the official publisher logo and the shared automation node renderer.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const TaplioIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/taplio.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const TaplioNode: NodeDefinition = {
    type: 'automation-taplio', category: 'social-media', label: 'Taplio',
    description: 'Draft, publish and schedule LinkedIn posts, queue comments and likes, read analytics and watch new activity',
    keywords: ['LinkedIn', 'social media', 'content', 'engagement'],
    Icon: TaplioIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TaplioIcon} iconColor="" />),
};
