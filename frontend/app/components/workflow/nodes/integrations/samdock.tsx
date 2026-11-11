import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const SamdockIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/samdock.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
SamdockIcon.displayName = 'SamdockIcon';

// Official publisher icon; provenance is recorded beside the SVG.
export const SamdockNode: NodeDefinition = {
    type: 'automation-samdock',
    label: 'Samdock',
    description: 'People, organizations, leads, deals and tasks',
    category: 'crm-sales',
    Icon: SamdockIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SamdockIcon} iconColor="" />),
};
