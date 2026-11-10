import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const ListenNotesIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/listennotes.svg" dark="/icons/listennotes-dark.svg" className={className} style={style} />
);

export const ListenNotesNode: NodeDefinition = {
    type: 'automation-listennotes', category: 'content-research', label: 'Listen Notes',
    description: 'Search podcasts and episodes, discover recommendations, and manage playlists',
    keywords: ['listennotes', 'podcast', 'listen later'],
    Icon: ListenNotesIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ListenNotesIcon} iconColor="" />),
};
