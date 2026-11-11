// Makes YouTrack available in the workflow canvas and integration catalog.
// Uses JetBrains' app mark with a matching dark theme variant for contrast.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const YouTrackIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/youtrack.svg" dark="/icons/youtrack-dark.svg" className={className} style={style} />
);

export const YouTrackNode: NodeDefinition = {
    type: 'automation-youtrack', category: 'developer-tools', label: 'YouTrack',
    description: 'Automate issues, comments, tags and time tracking, and watch for issue changes',
    keywords: ['JetBrains', 'issue tracker', 'bug tracker', 'project management'],
    Icon: YouTrackIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={YouTrackIcon} iconColor="" />),
};
