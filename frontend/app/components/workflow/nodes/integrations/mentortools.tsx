import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const MentortoolsIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/mentortools.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);

export const MentortoolsNode: NodeDefinition = {
    type: 'automation-mentortools', category: 'courses', label: 'Mentortools',
    description: 'Manage courses, lessons, buyer access, payments and media',
    Icon: MentortoolsIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MentortoolsIcon} iconColor="" />),
};
