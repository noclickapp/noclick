// Native Keila campaign/template metadata node with the original official logo.
// Credential and operation forms are driven by the provider's generated schema.
import { forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://www.keila.io
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/keila-brand-vector.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

const KeilaIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => <img ref={ref} src="/icons/keila.svg" alt="" className={className} style={style} {...props} />
);
KeilaIcon.displayName = 'KeilaIcon';
const KeilaNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />;
export const KeilaNode: NodeDefinition = {
    type: 'automation-keila', category: 'marketing', label: 'Keila',
    description: 'Keila campaign and template metadata reads',
    Icon: OfficialBrandIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: KeilaNodeComponent,
};
