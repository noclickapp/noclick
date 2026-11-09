import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const PadletIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/padlet-1.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const PadletNode: NodeDefinition = {
    type: 'automation-padlet-1', category: 'productivity', label: 'Padlet',
    description: 'Read boards and organization analytics, create posts, comments and reactions, and watch recent organization signups',
    Icon: PadletIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PadletIcon} iconColor="" />),
};
