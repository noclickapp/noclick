// FieldView operations and scheduled agronomic activity monitoring.
// The official publisher icon is used unchanged; its source is recorded beside it.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const ClimateIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg light="/icons/climate.svg" className={className} style={style} {...props} ref={ref} />),
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
