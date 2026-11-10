import { forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

import type { CSSProperties as BrandCSSProperties } from 'react';
// Statuspal path from Simple Icons; see statuspal.provenance.md.
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/statuspal-brand-vector.svg" alt="" aria-hidden="true" className={(className || '') + ' [--brand-invert:0] dark:[--brand-invert:1]'}
        style={{ ...style, objectFit: 'contain' } as BrandCSSProperties} />
);

const StatusPalIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => <img ref={ref} src="/icons/statuspal.png" alt="" className={className} style={style} {...props} />
);
StatusPalIcon.displayName = 'StatusPalIcon';
const StatusPalNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />;
export const StatusPalNode: NodeDefinition = {
    type: 'automation-statuspal', category: 'monitoring', label: 'StatusPal',
    description: 'StatusPal protected status-page and service metadata reads',
    Icon: OfficialBrandIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: StatusPalNodeComponent,
};
