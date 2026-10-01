import { forwardRef, memo } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from './types';

const Icon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/google-classroom.svg" alt="" className={className} style={style} {...props} />
    ),
);
Icon.displayName = 'GoogleClassroomIcon';

export const GoogleClassroomNode: NodeDefinition = {
    type: 'automation-google-classroom',
    label: 'Google Classroom',
    description: 'Manage courses, assignments, announcements, topics and rosters',
    Icon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 46 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={Icon} iconColor="" />),
};
