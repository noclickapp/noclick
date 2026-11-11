// Fountain Private Hire reads opening, stage and applicant metadata and manages
// ordinary applicant records. Creation disables the four communication consents;
// Fountain One and hiring transitions are separate contracts.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
// Vector brand artwork from https://fountain.com

// Sourced brand artwork: https://fountain.com
const PreferredBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <ThemedBrandImg light="/icons/fountain-preferred-brand.svg" dark="/icons/fountain-preferred-brand-dark.svg" className={className} style={style} />
);

const FountainIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/fountain.svg" alt="" className={className} style={style} {...props} />
    ),
);
FountainIcon.displayName = 'FountainIcon';

export const FountainNode: NodeDefinition = {
    type: 'automation-fountain',
    label: 'Fountain',
    description: 'Fountain Private Hire openings, stages and applicant records',
    category: 'hr-recruiting',
    Icon: PreferredBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PreferredBrandIcon} iconColor="" />),
};
