import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const AviatoIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg light="/icons/aviato.svg" dark="/icons/aviato-dark.svg" className={className} style={style} {...props} ref={ref} />
    ),
);
AviatoIcon.displayName = 'AviatoIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const AviatoNode: NodeDefinition = {
    type: 'automation-aviato',
    label: 'Aviato',
    description: 'Enrich companies and people, search prospects and generate market maps',
    category: 'crm-sales',
    Icon: AviatoIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AviatoIcon} iconColor="" />),
};
