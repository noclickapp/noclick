import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const LessonspaceIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/lessonspace.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const LessonspaceNode: NodeDefinition = {
    type: 'automation-lessonspace', category: 'courses', label: 'Lessonspace',
    description: 'Manage lesson spaces, sessions, participants and recordings',
    Icon: LessonspaceIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={LessonspaceIcon} iconColor="" />),
};
