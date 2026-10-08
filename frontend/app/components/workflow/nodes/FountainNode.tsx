// Fountain Private Hire reads opening, stage and applicant metadata and manages
// ordinary applicant records. Creation disables the four communication consents;
// Fountain One and hiring transitions are separate contracts.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';


// Unmodified compact brand asset from https://www.fountain.com/in/fountain-india
import type { CSSProperties as BrandCSSProperties } from 'react';
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/fountain-brand.webp" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
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
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />),
};
