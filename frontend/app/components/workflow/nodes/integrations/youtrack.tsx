// Makes YouTrack available in the workflow canvas and integration catalog.
// Uses JetBrains' app mark with a matching dark theme variant for contrast.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const YouTrackIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <>
        <img src="/icons/youtrack.svg" alt="" aria-hidden="true" className={`${className ?? ''} dark:hidden`} style={style} />
        <img src="/icons/youtrack-dark.svg" alt="" aria-hidden="true" className={`${className ?? ''} hidden dark:block`} style={style} />
    </>
);

export const YouTrackNode: NodeDefinition = {
    type: 'automation-youtrack', category: 'developer-tools', label: 'YouTrack',
    description: 'Automate issues, comments, tags and time tracking, and watch for issue changes',
    keywords: ['JetBrains', 'issue tracker', 'bug tracker', 'project management'],
    Icon: YouTrackIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={YouTrackIcon} iconColor="" />),
};
