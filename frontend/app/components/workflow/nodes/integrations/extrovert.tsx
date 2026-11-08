import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const ExtrovertIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/extrovert.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
ExtrovertIcon.displayName = 'ExtrovertIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const ExtrovertNode: NodeDefinition = {
    type: 'automation-extrovert',
    label: 'Extrovert',
    description: 'Automate LinkedIn campaigns, prospects, comments and direct messages',
    category: 'social-media',
    Icon: ExtrovertIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ExtrovertIcon} iconColor="" />),
};
