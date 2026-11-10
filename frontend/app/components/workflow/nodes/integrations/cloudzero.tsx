import { forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://cloudzero.com

// Sourced brand artwork: https://www.cloudzero.com/
const PreferredBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/cloudzero-preferred-brand.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
);

const CloudZeroIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => <img ref={ref} src="/icons/cloudzero.svg" alt="" className={className} style={style} {...props} />
);
CloudZeroIcon.displayName = 'CloudZeroIcon';
const CloudZeroNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={PreferredBrandIcon} iconColor="" />;
export const CloudZeroNode: NodeDefinition = {
    type: 'automation-cloudzero', category: 'cloud-hosting', label: 'CloudZero',
    description: 'CloudZero cost, dimension and saved-view metadata reads',
    Icon: PreferredBrandIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: CloudZeroNodeComponent,
};
