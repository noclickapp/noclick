import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const TalenthrIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/talenthr.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
TalenthrIcon.displayName = 'TalenthrIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const TalenthrNode: NodeDefinition = {
    type: 'automation-talenthr',
    label: 'TalentHR',
    description: 'Employees, departments, locations and time off',
    Icon: TalenthrIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TalenthrIcon} iconColor="" />),
};
