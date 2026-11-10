import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const GoToWebinarIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/gotowebinar.svg" dark="/icons/gotowebinar-dark.svg" className={className} style={style} />
);

export const GoToWebinarNode: NodeDefinition = {
    type: 'automation-gotowebinar', category: 'meetings', label: 'GoTo Webinar',
    description: 'Schedule webinars, register participants and read attendee reports',
    Icon: GoToWebinarIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={GoToWebinarIcon} iconColor="" />),
};
