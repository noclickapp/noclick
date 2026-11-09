// Defines Strale in the workflow catalogue and canvas. The official icon identifies this integration.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const StraleIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/strale.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
StraleIcon.displayName = 'StraleIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const StraleNode: NodeDefinition = {
    type: 'automation-strale',
    label: 'Strale',
    description: 'Execute AI tools and solutions, track transactions and manage API keys',
    category: 'ai',
    Icon: StraleIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={StraleIcon} iconColor="" />),
};
