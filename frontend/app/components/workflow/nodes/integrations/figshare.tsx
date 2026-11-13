import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const FigshareIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg light="/icons/figshare.svg" className={className} style={style} {...props} ref={ref} />
    ),
);
FigshareIcon.displayName = 'FigshareIcon';

// Exact publisher asset; provenance is recorded beside the icon.
export const FigshareNode: NodeDefinition = {
    type: 'automation-figshare',
    label: 'Figshare',
    description: 'Research articles, datasets and collections',
    category: 'content-research',
    Icon: FigshareIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={FigshareIcon} iconColor="" />),
};
