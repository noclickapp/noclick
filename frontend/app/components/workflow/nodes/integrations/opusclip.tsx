import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const OpusClipIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/opusclip.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const OpusClipNode: NodeDefinition = {
    type: 'automation-opusclip', label: 'OpusClip', category: 'media',
    description: 'Create video clips, organize collections and publish social posts',
    keywords: ['Opus Clip', 'video', 'shorts', 'captions', 'thumbnail'],
    Icon: OpusClipIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OpusClipIcon} iconColor="" />),
};
