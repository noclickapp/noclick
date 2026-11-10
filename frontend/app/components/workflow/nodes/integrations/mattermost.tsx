import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const MattermostIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/mattermost.svg" dark="/icons/mattermost-dark.svg" className={className} style={style} />
);

export const MattermostNode: NodeDefinition = {
    type: 'automation-mattermost', category: 'communication', label: 'Mattermost',
    description: 'Automate Mattermost channels, messages, threads and reactions',
    Icon: MattermostIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MattermostIcon} iconColor="" />),
};
