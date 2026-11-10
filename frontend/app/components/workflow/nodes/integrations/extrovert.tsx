import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';


const ExtrovertIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg {...props} light="/icons/extrovert.svg" dark="/icons/extrovert-dark.svg" ref={ref} className={className} style={{ ...style, objectFit: 'contain' }} />
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
