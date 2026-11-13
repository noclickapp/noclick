import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const AworkIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/awork.svg" dark="/icons/awork-dark.svg" className={className} style={style} />
);

export const AworkNode: NodeDefinition = {
    type: 'automation-awork', category: 'productivity', label: 'awork',
    description: 'Automate projects, tasks, companies, comments and time entries',
    Icon: AworkIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AworkIcon} iconColor="" />),
};
