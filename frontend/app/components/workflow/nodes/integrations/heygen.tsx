import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const HeyGenIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/heygen.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const HeyGenNode: NodeDefinition = {
    type: 'automation-heygen', category: 'ai', label: 'HeyGen',
    description: 'Create avatar and template videos, translate videos, manage media, and start workflows when videos complete',
    Icon: HeyGenIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={HeyGenIcon} iconColor="" />),
};
