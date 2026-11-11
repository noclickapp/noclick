import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const AbyssHubIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <>
        <img src="/icons/abysshub.svg" alt="" className={`${className ?? ''} dark:hidden`} style={style} />
        <img src="/icons/abysshub-dark.svg" alt="" className={`${className ?? ''} hidden dark:block`} style={style} />
    </>
);

export const AbyssHubNode: NodeDefinition = {
    type: 'automation-abysshub', category: 'developer-tools', label: 'AbyssHub',
    description: 'Run Widgets, read results and files, and trigger workflows on new runs',
    keywords: ['Abyss', 'widgets', 'runs', 'automation'],
    Icon: AbyssHubIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AbyssHubIcon} iconColor="" />),
};
