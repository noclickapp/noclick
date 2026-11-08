// Linkwarden exposes closed collection/tag metadata reads in the native editor.
// The unchanged official PNG wordmark is separate from generated operation forms.
import { memo, forwardRef } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from './types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://linkwarden.app
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/linkwarden-brand-vector.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
);

const LinkwardenIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/linkwarden.png" alt="" className={className} style={{ ...style, objectFit: "contain" }} {...props} />
    ),
);
LinkwardenIcon.displayName = 'LinkwardenIcon';

export const LinkwardenNode: NodeDefinition = {
    type: 'automation-linkwarden',
    label: 'Linkwarden',
    description: 'Read scoped collection and tag metadata',
    category: 'productivity',
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />
    )),
};
