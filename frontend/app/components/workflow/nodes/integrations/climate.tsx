// FieldView operations and scheduled agronomic activity monitoring.
// The official publisher icon is used unchanged; its source is recorded beside it.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const ClimateIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/climate.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
ClimateIcon.displayName = 'ClimateIcon';

export const ClimateNode: NodeDefinition = {
    type: 'automation-climate',
    label: 'Climate FieldView',
    description: 'Fields, boundaries, scouting, agronomic activities, uploads and exports',
    keywords: ['climate', 'fieldview', 'agriculture', 'farming', 'planting', 'harvest'],
    category: 'industry',
    Icon: ClimateIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ClimateIcon} iconColor="" />),
};
