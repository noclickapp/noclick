// Hex data/BI automation node definition.
// Provides workflow integration with the Hex REST API (project runs, projects,
// sharing, embedding, admin users/groups/collections, data connections).

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const HexIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img ref={ref} src="/icons/hex.svg" alt="" className={className} style={style} {...props} />
));
HexIcon.displayName = 'HexIcon';

const HexNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={HexIcon} iconColor="" />;
};

export const HexNode: NodeDefinition = {
    type: 'automation-hex',
    label: 'Hex',
    description: 'Hex data and BI automation',
    Icon: HexIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(HexNodeComponent),
};
