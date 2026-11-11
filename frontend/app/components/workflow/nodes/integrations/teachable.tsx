import { forwardRef } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Teachable's app icon, traced from its Google Play listing; the provenance sits beside the SVG.
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/teachable.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const TeachableIcon: SvgIconComponent = forwardRef<
    HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>
>(({ style, ...props }, ref) => (
    <img {...props} ref={ref} src="/icons/teachable.svg" alt=""
        style={{ ...style, objectFit: 'contain' }} />
));
TeachableIcon.displayName = 'TeachableIcon';
const Component = (props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />;
export const TeachableNode: NodeDefinition = {
    type: 'automation-teachable', category: 'courses', label: 'Teachable',
    description: 'Course, student, enrollment and progress metadata with distinct Admin and user OAuth access',
    Icon: OfficialBrandIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 }, component: Component,
};
