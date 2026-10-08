// OpenStatus metadata node uses its exact official published vector asset.
// Native forms and selection come from the generated typed schema; no generic RPC editor.
import { forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';


// Unmodified compact brand asset from https://www.openstatus.dev
import type { CSSProperties as BrandCSSProperties } from 'react';
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/openstatus-brand.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
);

export const OpenStatusIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => <img ref={ref} src="/icons/openstatus.svg" alt="" className={className} style={style} {...props} />,
);
OpenStatusIcon.displayName = 'OpenStatusIcon';
export const OpenStatusNode: NodeDefinition = {
    type: 'automation-openstatus', label: 'OpenStatus', description: 'Protected monitoring and status-page metadata reads',
    Icon: OfficialBrandIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 },
    component: (props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />,
};
