import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ListenNotesIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/listennotes.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);

export const ListenNotesNode: NodeDefinition = {
    type: 'automation-listennotes', category: 'content-research', label: 'Listen Notes',
    description: 'Search podcasts and episodes, discover recommendations, and manage playlists',
    keywords: ['listennotes', 'podcast', 'listen later'],
    Icon: ListenNotesIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ListenNotesIcon} iconColor="" />),
};
