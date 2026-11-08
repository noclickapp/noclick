// Native Adobe Analytics 2.0 company-scoped reporting and component actions.
// The original Adobe documentation asset is displayed unchanged; configuration
// and credentials use the generated native schema and existing canvas forms.
import { forwardRef, memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const AdobeAnalyticsIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => <img ref={ref} src="/icons/adobe-analytics.svg" alt="" className={className} style={style} {...props} />
);
AdobeAnalyticsIcon.displayName = 'AdobeAnalyticsIcon';
const Component = (props: NodeProps) => <AutomationNode {...props} Icon={AdobeAnalyticsIcon} iconColor="" />;
export const AdobeAnalyticsNode: NodeDefinition = {
    type: 'automation-adobe-analytics', category: 'analytics-bi', label: 'Adobe Analytics',
    description: 'Analytics 2.0 discovery, suite metadata, reports and owned calculated metrics',
    Icon: AdobeAnalyticsIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(Component),
};
