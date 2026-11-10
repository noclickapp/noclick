import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const JustCallIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/justcall.svg" dark="/icons/justcall-dark.svg" className={className} style={style} />
);

export const JustCallNode: NodeDefinition = {
    type: 'automation-justcall', category: 'communication', label: 'JustCall',
    description: 'Manage contacts, calls, SMS messages, phone numbers and tags',
    Icon: JustCallIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={JustCallIcon} iconColor="" />),
};
