import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const BluebarryIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/bluebarry.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
BluebarryIcon.displayName = 'BluebarryIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const BluebarryNode: NodeDefinition = {
    type: 'automation-bluebarry',
    label: 'Bluebarry',
    description: 'Shopper profiles, quiz events and webhooks',
    category: 'ecommerce',
    Icon: BluebarryIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BluebarryIcon} iconColor="" />),
};
