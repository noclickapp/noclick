import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const TikHubIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/tik-hub.jpg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
TikHubIcon.displayName = 'TikHubIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const TikHubNode: NodeDefinition = {
    type: 'automation-tik-hub',
    label: 'Tik Hub',
    description: 'Social profiles, videos, comments, search and batch link extraction',
    category: 'social-media',
    Icon: TikHubIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TikHubIcon} iconColor="" />),
};
