import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const WodifyCoreIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/wodify-core.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const WodifyCoreNode: NodeDefinition = {
    type: 'automation-wodify-core', category: 'industry', label: 'Wodify Core',
    description: 'Manage Wodify clients, leads and tags; read classes, memberships and attendance',
    Icon: WodifyCoreIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={WodifyCoreIcon} iconColor="" />),
};
