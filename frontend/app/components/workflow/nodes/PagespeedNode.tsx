// Google PageSpeed Insights automation node definition.
// Runs Lighthouse + Chrome UX Report (CrUX) analyses for a URL via the
// PageSpeed Insights v5 API (scores, Core Web Vitals, lab metrics, opportunities).

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const PagespeedIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img ref={ref} src="/icons/pagespeed.svg" alt="" className={className} style={style} {...props} />
));
PagespeedIcon.displayName = 'PagespeedIcon';

const PagespeedNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={PagespeedIcon} iconColor="" />;
};

export const PagespeedNode: NodeDefinition = {
    type: 'automation-pagespeed',
    label: 'Google PageSpeed',
    description: 'Google PageSpeed Insights analysis',
    Icon: PagespeedIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(PagespeedNodeComponent),
};
