import { forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';


// Unmodified compact brand asset from https://connecteam.com
import type { CSSProperties as BrandCSSProperties } from 'react';
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/connecteam-brand.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
);

const ConnecteamIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/connecteam.svg"
        alt=""
        className={className}
        style={style}
        {...props}
    />
));
ConnecteamIcon.displayName = 'ConnecteamIcon';

export const ConnecteamNode: NodeDefinition = {
    type: 'automation-connecteam',
    label: 'Connecteam',
    description: 'Workforce scheduling, time tracking, tasks, forms, and users',
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: (props: NodeProps) => (
        <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />
    ),
};
