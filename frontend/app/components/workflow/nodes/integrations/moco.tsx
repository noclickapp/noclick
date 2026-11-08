// MOCO joins the workflow catalog through this self-registering definition.
// The provider's official app icon identifies its CRM and time-tracking actions.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const MocoIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/moco.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
MocoIcon.displayName = 'MocoIcon';

export const MocoNode: NodeDefinition = {
    type: 'automation-moco',
    label: 'MOCO',
    description: 'Manage customers, contacts, projects, time entries, deals and invoices',
    keywords: ['moco', 'mocoapp', 'crm', 'time tracking', 'agency'],
    Icon: MocoIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MocoIcon} iconColor="" />),
};
