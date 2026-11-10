import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const JiraServiceManagementAlertIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/jira-service-management-alert-ca.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
JiraServiceManagementAlertIcon.displayName = 'JiraServiceManagementAlertIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const JiraServiceManagementAlertNode: NodeDefinition = {
    type: 'automation-jira-service-management-alert-ca',
    label: 'Jira Service Management Alert',
    description: 'Create, acknowledge and manage Operations alerts, notes and new-alert polling',
    category: 'monitoring',
    Icon: JiraServiceManagementAlertIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={JiraServiceManagementAlertIcon} iconColor="" />),
};
