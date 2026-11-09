import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ReflectIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/reflect.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const ReflectNode: NodeDefinition = {
    type: 'automation-reflect', category: 'productivity', label: 'Reflect',
    description: 'Create notes, append daily notes and manage bookmarked links',
    Icon: ReflectIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ReflectIcon} iconColor="" />),
};
