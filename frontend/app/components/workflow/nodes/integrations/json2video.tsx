import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const JSON2VideoIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/json2video.svg" alt="" aria-hidden="true" className={className} style={style} />
);

export const JSON2VideoNode: NodeDefinition = {
    type: 'automation-json2video', category: 'media', label: 'JSON2Video API',
    description: 'Render videos, manage templates and media, convert subtitles, and watch for new movies or finished renders',
    keywords: ['video', 'render', 'template', 'subtitles', 'json2video'],
    Icon: JSON2VideoIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={JSON2VideoIcon} iconColor="" />),
};
