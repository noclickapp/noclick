// Adds api.video to the integration catalog and workflow canvas.
// Configuration and credentials come from the generated backend schema.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const VideoIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/video.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);

export const VideoNode: NodeDefinition = {
    type: 'automation-video', category: 'media', label: 'api.video',
    description: 'Import and manage videos, live streams, captions and signed video events',
    keywords: ['apivideo', 'video hosting', 'streaming', 'encoding'],
    Icon: VideoIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={VideoIcon} iconColor="" />),
};
