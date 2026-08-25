// Pipedrive CRM automation node definition.
// Provides workflow integration with the Pipedrive v2/v1 API (deals, persons,
// organizations, activities, leads, notes, products) plus a webhook trigger.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const PipedriveIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img ref={ref} src="/icons/pipedrive.svg" alt="" className={className} style={style} {...props} />
));
PipedriveIcon.displayName = 'PipedriveIcon';

const PipedriveNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={PipedriveIcon} iconColor="" />;
};

export const PipedriveNode: NodeDefinition = {
    type: 'automation-pipedrive',
    label: 'Pipedrive',
    description: 'Pipedrive CRM automation',
    Icon: PipedriveIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(PipedriveNodeComponent),
};
