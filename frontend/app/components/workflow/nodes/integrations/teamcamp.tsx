/** Registers Teamcamp in the integration catalog and workflow canvas.
 * Its official icon identifies project and task automations in the Productivity section. */
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const TeamcampIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/teamcamp.svg" dark="/icons/teamcamp-dark.svg" className={className} style={style} />
);

export const TeamcampNode: NodeDefinition = {
    type: 'automation-teamcamp', category: 'productivity', label: 'Teamcamp',
    description: 'Manage Teamcamp projects, tasks, comments, groups and workspace contacts',
    Icon: TeamcampIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TeamcampIcon} iconColor="" />),
};
