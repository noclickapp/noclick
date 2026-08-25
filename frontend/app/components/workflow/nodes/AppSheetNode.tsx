// Google AppSheet automation node definition.
// Provides workflow integration with the AppSheet v2 REST API (add/edit/delete
// rows, find rows via Selector expressions, invoke custom actions) plus a
// webhook trigger for AppSheet Automation bot events.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const AppSheetIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img ref={ref} src="/icons/appsheet.svg" alt="" className={className} style={style} {...props} />
));
AppSheetIcon.displayName = 'AppSheetIcon';

const AppSheetNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={AppSheetIcon} iconColor="" />;
};

export const AppSheetNode: NodeDefinition = {
    type: 'automation-appsheet',
    label: 'Google AppSheet',
    description: 'Google AppSheet table automation',
    Icon: AppSheetIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(AppSheetNodeComponent),
};
