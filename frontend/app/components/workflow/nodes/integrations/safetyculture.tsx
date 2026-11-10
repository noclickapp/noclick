import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const SafetyCultureIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg light="/icons/safetyculture.svg" dark="/icons/safetyculture-dark.svg" className={className} style={style} {...props} ref={ref} />
    ),
);
SafetyCultureIcon.displayName = 'SafetyCultureIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const SafetyCultureNode: NodeDefinition = {
    type: 'automation-safetyculture',
    label: 'SafetyCulture',
    keywords: ['Mitti', 'iAuditor'],
    description: 'Inspections, templates and actions in SafetyCulture (now Mitti)',
    category: 'industry',
    Icon: SafetyCultureIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SafetyCultureIcon} iconColor="" />),
};
