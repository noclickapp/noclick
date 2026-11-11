import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const AworkIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <>
        <img src="/icons/awork.svg" alt="" aria-hidden="true"
            className={`dark:hidden ${className ?? ''}`} style={style} />
        <img src="/icons/awork-dark.svg" alt="" aria-hidden="true"
            className={` hidden dark:block ${className ?? ''}`} style={style} />
    </>
);

export const AworkNode: NodeDefinition = {
    type: 'automation-awork', category: 'productivity', label: 'awork',
    description: 'Automate projects, tasks, companies, comments and time entries',
    Icon: AworkIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AworkIcon} iconColor="" />),
};
