// OpenStatus metadata node uses its exact official published vector asset.
// Native forms and selection come from the generated typed schema; no generic RPC editor.
import { forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://www.openstatus.dev
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/openstatus.svg" alt="" aria-hidden="true" className={(className || '') + ' [--brand-invert:0] dark:[--brand-invert:1]'}
        style={{ ...style, objectFit: 'contain' } as BrandCSSProperties} />
);

export const OpenStatusIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => <img ref={ref} src="/icons/openstatus.svg" alt="" className={className} style={style} {...props} />,
);
OpenStatusIcon.displayName = 'OpenStatusIcon';
export const OpenStatusNode: NodeDefinition = {
    type: 'automation-openstatus', category: 'monitoring', label: 'OpenStatus', description: 'Protected monitoring and status-page metadata reads',
    Icon: OfficialBrandIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 },
    component: (props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />,
};
