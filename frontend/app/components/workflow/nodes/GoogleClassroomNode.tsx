import { forwardRef, memo } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from './types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://classroom.google.com

// Sourced brand artwork: https://logos.composio.dev/api/google_classroom
const PreferredBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/google-classroom-preferred-brand.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
);

const Icon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/google-classroom.svg" alt="" className={className} style={style} {...props} />
    ),
);
Icon.displayName = 'GoogleClassroomIcon';

export const GoogleClassroomNode: NodeDefinition = {
    type: 'automation-google-classroom',
    label: 'Google Classroom',
    description: 'Manage courses, assignments, announcements, topics and rosters',
    category: 'google',
    Icon: PreferredBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 46 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PreferredBrandIcon} iconColor="" />),
};
