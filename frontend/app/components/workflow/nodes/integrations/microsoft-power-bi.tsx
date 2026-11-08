// Power BI's self-registering canvas and catalog definition.
// The publisher's icon is shipped unchanged with a provenance sidecar.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const PowerBIIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/microsoft-power-bi.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
PowerBIIcon.displayName = 'PowerBIIcon';

export const MicrosoftPowerBINode: NodeDefinition = {
    type: 'automation-microsoft-power-bi',
    label: 'Microsoft Power BI',
    category: 'analytics-bi',
    description: 'Manage datasets, push rows, refresh data, query DAX, and manage reports and dashboards',
    Icon: PowerBIIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PowerBIIcon} iconColor="" />),
};
