import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const RitekitIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/ritekit.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const RitekitNode: NodeDefinition = {
    type: 'automation-ritekit', category: 'social-media', label: 'RiteKit',
    description: 'Research hashtags, enrich posts, create quote images and shorten links',
    Icon: RitekitIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={RitekitIcon} iconColor="" />),
};
