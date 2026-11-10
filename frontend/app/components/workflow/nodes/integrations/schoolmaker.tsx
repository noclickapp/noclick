import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SchoolMakerIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/schoolmaker.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const SchoolMakerNode: NodeDefinition = {
    type: 'automation-schoolmaker', category: 'courses', label: 'SchoolMaker',
    description: 'Manage members, programs, offers, coaching, conversations and community content',
    Icon: SchoolMakerIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SchoolMakerIcon} iconColor="" />),
};
