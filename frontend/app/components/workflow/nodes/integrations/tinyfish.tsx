import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const TinyfishIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/tinyfish.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const TinyfishNode: NodeDefinition = {
    type: 'automation-tinyfish', category: 'content-research', label: 'Tinyfish',
    description: 'Automate browser tasks, extract web content, research, and manage datasets and monitors',
    Icon: TinyfishIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TinyfishIcon} iconColor="" />),
};
