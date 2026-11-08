// Superwall reads scoped project, application and subscription-definition metadata.
// This native editor definition uses the exact official favicon without tinting.
import { forwardRef, memo } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';
const SuperwallIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => <img ref={ref} src="/icons/superwall.svg" alt="" className={className} style={style} {...props} />,
);
SuperwallIcon.displayName = 'SuperwallIcon';
export const SuperwallNode: NodeDefinition = {
    type: 'automation-superwall', label: 'Superwall',
    description: 'Read scoped organization, project, product, entitlement and aggregate chart metadata',
    keywords: ['Superwall', 'projects', 'applications', 'products', 'entitlements', 'charts', 'subscriptions'],
    Icon: SuperwallIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SuperwallIcon} iconColor="" />),
};
