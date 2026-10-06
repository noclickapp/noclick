import { forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

// Original vendor wordmark; docs/engineering/bloomerang-icon-provenance.md.
const BloomerangIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => <img ref={ref} src="/icons/bloomerang.svg" alt="" className={className} style={{ objectFit: 'contain', ...style }} {...props} />,
);
BloomerangIcon.displayName = 'BloomerangIcon';
const BloomerangNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={BloomerangIcon} iconColor="" />;

export const BloomerangNode: NodeDefinition = {
    type: 'automation-bloomerang',
    label: 'Bloomerang',
    description: 'Constituents, households, interaction records and plain notes',
    Icon: BloomerangIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: BloomerangNodeComponent,
};
