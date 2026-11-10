// Native BoldSign document/template metadata and owned contact workflows.
// The official developer wordmark is retained exactly and displayed in full.
import { forwardRef, memo } from 'react';
import type { ImgHTMLAttributes } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://boldsign.com
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/boldsign-brand-vector.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

const BoldSignIcon: SvgIconComponent = forwardRef<HTMLImageElement, ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => <img ref={ref} {...props} src="/icons/boldsign.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} />,
);
BoldSignIcon.displayName = 'BoldSignIcon';

export const BoldSignNode: NodeDefinition = {
    type: 'automation-boldsign', category: 'documents', label: 'BoldSign',
    description: 'Read scoped document and template metadata; manage owned contacts and tags',
    Icon: OfficialBrandIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />),
};
