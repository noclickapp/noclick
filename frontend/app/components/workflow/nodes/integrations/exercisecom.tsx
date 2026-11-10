import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const ExercisecomIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/exercisecom.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
ExercisecomIcon.displayName = 'ExercisecomIcon';

// Exact publisher asset; provenance is recorded beside the PNG.
export const ExercisecomNode: NodeDefinition = {
    type: 'automation-exercisecom',
    label: 'Exercise.com',
    description: 'Manage workout calendars, member profiles, memberships, attendance and staff tasks',
    category: 'industry',
    Icon: ExercisecomIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo(function ExercisecomComponent(props: NodeProps) {
        return <AutomationNode {...props} Icon={ExercisecomIcon} iconColor="" />;
    }),
};
