import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const AbyssHubIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/abysshub.svg" dark="/icons/abysshub-dark.svg" className={className} style={style} />
);

export const AbyssHubNode: NodeDefinition = {
    type: 'automation-abysshub', category: 'developer-tools', label: 'AbyssHub',
    description: 'Run Widgets, read results and files, and trigger workflows on new runs',
    keywords: ['Abyss', 'widgets', 'runs', 'automation'],
    Icon: AbyssHubIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AbyssHubIcon} iconColor="" />),
};
