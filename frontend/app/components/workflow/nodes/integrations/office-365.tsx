import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const Office365Icon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/office-365.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
Office365Icon.displayName = 'Office365Icon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const Office365Node: NodeDefinition = {
    type: 'automation-office-365',
    label: 'Microsoft Office 365',
    description: 'Automate Outlook mail, calendars and contacts with Microsoft Graph',
    category: 'microsoft',
    Icon: Office365Icon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={Office365Icon} iconColor="" />),
};
