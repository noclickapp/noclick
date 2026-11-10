import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const VideoDbIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/video-db.svg" dark="/icons/video-db-dark.svg" className={className} style={style} />
);

export const VideoDbNode: NodeDefinition = {
    type: 'automation-video-db', category: 'media', label: 'VideoDB',
    description: 'Manage collections, upload media, search and process videos',
    keywords: ['Video Db', 'video database', 'transcription', 'semantic video search'],
    Icon: VideoDbIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={VideoDbIcon} iconColor="" />),
};
