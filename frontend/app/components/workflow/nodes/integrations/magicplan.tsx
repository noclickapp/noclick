import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const MagicplanIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <>
        <img src="/icons/magicplan.svg" alt="" aria-hidden="true" className={`${className ?? ''} dark:hidden`}
            style={{ ...style, objectFit: 'contain' } as CSSProperties} />
        <img src="/icons/magicplan-dark.svg" alt="" aria-hidden="true" className={`${className ?? ''} hidden dark:block`}
            style={{ ...style, objectFit: 'contain' } as CSSProperties} />
    </>
);

export const MagicplanNode: NodeDefinition = {
    type: 'automation-magicplan', category: 'industry', label: 'magicplan',
    description: 'Manage projects, plans, teams and exports; watch project exports',
    Icon: MagicplanIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MagicplanIcon} iconColor="" />),
};
