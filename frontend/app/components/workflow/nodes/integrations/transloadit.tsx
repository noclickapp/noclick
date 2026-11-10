import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const TransloaditIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg light="/icons/transloadit.svg" dark="/icons/transloadit-dark.svg" className={className} style={style} {...props} ref={ref} />
    ),
);
TransloaditIcon.displayName = 'TransloaditIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const TransloaditNode: NodeDefinition = {
    type: 'automation-transloadit',
    label: 'Transloadit',
    category: 'media',
    description: 'Automate media processing, Assemblies, Templates and credential metadata',
    Icon: TransloaditIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TransloaditIcon} iconColor="" />),
};
