import { forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://mediasilo.com
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/mediasilo-brand-vector.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

const MediaSiloIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => <img ref={ref} src="/icons/mediasilo.svg" alt="" className={className} style={style} {...props} />
);
MediaSiloIcon.displayName = 'MediaSiloIcon';
const MediaSiloNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />;
export const MediaSiloNode: NodeDefinition = {
    type: 'automation-mediasilo', category: 'media', label: 'MediaSilo',
    description: 'MediaSilo protected project and folder metadata reads',
    Icon: OfficialBrandIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: MediaSiloNodeComponent,
};
