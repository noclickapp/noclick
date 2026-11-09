import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const NextdoorIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/nextdoor.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
NextdoorIcon.displayName = 'NextdoorIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const NextdoorNode: NodeDefinition = {
    type: 'automation-nextdoor',
    label: 'Nextdoor',
    description: 'Publish posts, listings and comments on Nextdoor',
    category: 'social-media',
    Icon: NextdoorIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={NextdoorIcon} iconColor="" />),
};
