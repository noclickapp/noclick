import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const FeathrIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/feathr.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
FeathrIcon.displayName = 'FeathrIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const FeathrNode: NodeDefinition = {
    type: 'automation-feathr',
    label: 'Feathr',
    description: 'Contacts, campaigns, projects, tags and custom fields',
    category: 'marketing',
    Icon: FeathrIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={FeathrIcon} iconColor="" />),
};
