// BambooHR (HRIS) automation node definition.
// Provides workflow integration with the BambooHR REST API: employees, tables,
// time off, time tracking, reports, files, metadata, webhooks, and an
// on-field-change push trigger. Authenticated with an API key or OAuth.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const BambooHRIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img ref={ref} src="/icons/bamboohr.svg" alt="" className={className} style={style} {...props} />
));
BambooHRIcon.displayName = 'BambooHRIcon';

const BambooHRNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={BambooHRIcon} iconColor="" />;
};

export const BambooHRNode: NodeDefinition = {
    type: 'automation-bamboohr',
    label: 'BambooHR',
    description: 'BambooHR HRIS automation',
    Icon: BambooHRIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(BambooHRNodeComponent),
};
