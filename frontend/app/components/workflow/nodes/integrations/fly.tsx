// Fly integration catalog and canvas definition. Backend-generated schemas supply
// the operation and credential forms; the icon is the official Fly brand asset.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const FlyIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/fly.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
FlyIcon.displayName = 'FlyIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const FlyNode: NodeDefinition = {
    type: 'automation-fly',
    label: 'Fly',
    description: 'Manage Fly apps, Machines and persistent volumes',
    category: 'cloud-hosting',
    Icon: FlyIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={FlyIcon} iconColor="" />),
};
