// Defines the Sidetracker node in the canvas and integration catalog.
// Uses the provider icon and generated backend configuration schema.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const SidetrackerIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/sidetracker.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
SidetrackerIcon.displayName = 'SidetrackerIcon';

// Exact publisher asset; provenance is recorded beside the PNG.
export const SidetrackerNode: NodeDefinition = {
    type: 'automation-sidetracker',
    label: 'Sidetracker',
    description: 'Lists, lead sessions, visits, notes and conversions',
    category: 'marketing',
    Icon: SidetrackerIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SidetrackerIcon} iconColor="" />),
};
