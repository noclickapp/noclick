// Exa AI search & web-retrieval automation node definition.
// Provides workflow integration with the Exa REST API (search, get contents,
// answer, find similar, agent runs, monitors, websets, team management) plus a
// webhook trigger for scheduled monitor results.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const ExaIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img ref={ref} src="/icons/exa.svg" alt="" className={className} style={style} {...props} />
));
ExaIcon.displayName = 'ExaIcon';

const ExaNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={ExaIcon} iconColor="" />;
};

export const ExaNode: NodeDefinition = {
    type: 'automation-exa',
    label: 'Exa',
    description: 'Exa AI search & web-retrieval automation',
    Icon: ExaIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(ExaNodeComponent),
};
