import { forwardRef, memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://www.ashbyhq.com

// Sourced brand artwork: https://www.ashbyhq.com
const PreferredBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/ashby-preferred-brand.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

const AshbyIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/ashby.svg"
        alt=""
        className={className}
        style={style}
        {...props}
    />
));
AshbyIcon.displayName = 'AshbyIcon';

export const AshbyNode: NodeDefinition = {
    type: 'automation-ashby',
    label: 'Ashby',
    description: 'Manage candidates, applications, jobs, and job postings',
    Icon: PreferredBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={PreferredBrandIcon} iconColor="" />
    )),
};
