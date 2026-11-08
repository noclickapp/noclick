// Immich exposes closed album metadata reads in the native editor.
// The unchanged official PNG icon is separate from generated operation forms.
import { memo, forwardRef } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from './types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://immich.app
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/immich-brand-vector.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
);

const ImmichIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/immich.png" alt="" className={className} style={{ ...style, objectFit: "contain" }} {...props} />
    ),
);
ImmichIcon.displayName = 'ImmichIcon';

export const ImmichNode: NodeDefinition = {
    type: 'automation-immich',
    label: 'Immich',
    description: 'Read scoped album metadata',
    category: 'media',
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />
    )),
};
