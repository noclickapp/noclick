import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const DirectIQIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/directiq.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
DirectIQIcon.displayName = 'DirectIQIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const DirectIQNode: NodeDefinition = {
    type: 'automation-directiq',
    label: 'DirectIQ',
    description: 'Automate email contacts, lists, campaigns and templates',
    category: 'marketing',
    Icon: DirectIQIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={DirectIQIcon} iconColor="" />),
};
