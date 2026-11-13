// TrackingMore courier discovery, existing shipment reads and scheduled updates.
// Self-registration keeps this integration independent of the shared node catalog.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const TrackingMoreIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => <ThemedBrandImg light="/icons/trackingmore.svg" dark="/icons/trackingmore-dark.svg" className={className} style={style} {...props} ref={ref} />);
TrackingMoreIcon.displayName = 'TrackingMoreIcon';
const TrackingMoreNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={TrackingMoreIcon} iconColor="" />;

export const TrackingMoreNode: NodeDefinition = {
    type: 'automation-trackingmore', category: 'ecommerce', label: 'TrackingMore', description: 'Courier discovery, shipment results and shipment update polling',
    Icon: TrackingMoreIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 }, component: memo(TrackingMoreNodeComponent),
};
