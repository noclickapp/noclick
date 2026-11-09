import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const VirtuousCRMIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/virtuous-crm.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
VirtuousCRMIcon.displayName = 'VirtuousCRMIcon';

export const VirtuousCRMNode: NodeDefinition = {
    type: 'automation-virtuous-crm',
    label: 'Virtuous CRM',
    description: 'Manage nonprofit contacts, notes, tags, gifts, projects and events',
    category: 'nonprofit',
    keywords: ['donors', 'fundraising', 'charity'],
    Icon: VirtuousCRMIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={VirtuousCRMIcon} iconColor="" />),
};
