// Cursor automation node definition.
// Provides workflow integration with the Cursor REST API (cloud agents, runs,
// admin/team, analytics) plus a webhook trigger for agent status changes.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const CursorIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <ThemedBrandImg light="/icons/cursor.svg" dark="/icons/cursor-dark.svg" className={className} style={style} {...props} ref={ref} />
));
CursorIcon.displayName = 'CursorIcon';

const CursorNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={CursorIcon} iconColor="" />;
};

export const CursorNode: NodeDefinition = {
    type: 'automation-cursor',
    label: 'Cursor',
    description: 'Cursor cloud agents and analytics automation',
    Icon: CursorIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(CursorNodeComponent),
};
