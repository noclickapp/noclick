// Traditional Printful catalog, bound-store metadata and unsubmitted draft node.
// Preserve the publisher's original colored SVG and the canvas supplied filter.
import { forwardRef, memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://printful.com
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/printful.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const PrintfulIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ style, ...props }, ref) => <img {...props} ref={ref} src="/icons/printful.svg" alt="" style={{ ...style, objectFit: 'contain' }} />,
);
PrintfulIcon.displayName = 'PrintfulIcon';
const PrintfulNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />;
export const PrintfulNode: NodeDefinition = {
    type: 'automation-printful', category: 'ecommerce', label: 'Printful', description: 'Traditional Printful catalog, store and draft order metadata',
    Icon: OfficialBrandIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 }, component: memo(PrintfulNodeComponent),
};
