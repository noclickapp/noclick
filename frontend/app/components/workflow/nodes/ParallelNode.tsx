// Parallel web-research automation node definition.
// Provides workflow integration with the Parallel API (search, extract, deep
// research tasks, FindAll entity discovery, monitors, chat) plus a webhook
// trigger for Task / Monitor completion events.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const ParallelIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>((props, ref) => (
    <ThemedBrandImg ref={ref} light="/icons/parallel-light.svg" dark="/icons/parallel.svg" {...props} />
));
ParallelIcon.displayName = 'ParallelIcon';

const ParallelNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={ParallelIcon} iconColor="" />;
};

export const ParallelNode: NodeDefinition = {
    type: 'automation-parallel',
    label: 'Parallel',
    description: 'Parallel web search and research automation',
    Icon: ParallelIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(ParallelNodeComponent),
};
