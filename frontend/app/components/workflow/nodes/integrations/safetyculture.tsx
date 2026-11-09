import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const SafetyCultureIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/safetyculture.svg" alt="" className={className} style={{ ...style, backgroundColor: '#1c1714', borderRadius: 8, padding: 4, objectFit: 'contain' }} {...props} />
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
