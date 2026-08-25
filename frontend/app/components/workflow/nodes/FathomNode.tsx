// Fathom meeting-notetaker automation node definition.
// Provides workflow integration with the Fathom external REST API (meetings,
// recordings, teams, webhooks) plus a webhook trigger for new-meeting events.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

export const FathomIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img ref={ref} src="/icons/fathom.svg" alt="" className={className} style={style} {...props} />
));
FathomIcon.displayName = 'FathomIcon';

const FathomNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={FathomIcon} iconColor="" />;
};

export const FathomNode: NodeDefinition = {
    type: 'automation-fathom',
    label: 'Fathom',
    description: 'Fathom meeting notetaker automation',
    Icon: FathomIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(FathomNodeComponent),
};
