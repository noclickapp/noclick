import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const TidyIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg light="/icons/tidy.svg" dark="/icons/tidy-dark.svg" className={className} style={style} {...props} ref={ref} />
    ),
);
TidyIcon.displayName = 'TidyIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const TidyNode: NodeDefinition = {
    type: 'automation-tidy',
    label: 'Tidy',
    category: 'nonprofit',
    keywords: ['TidyHQ'],
    description: 'TidyHQ contacts, memberships, events and invoices',
    Icon: TidyIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TidyIcon} iconColor="" />),
};
