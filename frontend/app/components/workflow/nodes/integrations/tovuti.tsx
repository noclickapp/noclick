// Tovuti LMS is discovered from this definition and its generated metadata.
// It exposes learner management, learning content, and scheduled progress events.
import { memo, type CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const TovutiIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/tovuti.svg"
        alt=""
        aria-hidden="true"
        className={className}
        style={
            {
                ...style,
                objectFit: 'contain',
            } as CSSProperties
        }
    />
);

export const TovutiNode: NodeDefinition = {
    type: 'automation-tovuti',
    category: 'courses',
    label: 'Tovuti LMS',
    description:
        'Manage learners, courses, assignments, groups and progress; watch LMS changes',
    Icon: TovutiIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={TovutiIcon} iconColor="" />
    )),
};
