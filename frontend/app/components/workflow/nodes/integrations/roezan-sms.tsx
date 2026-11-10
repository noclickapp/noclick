import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const RoezanSMSIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/roezan-sms.svg" dark="/icons/roezan-sms-dark.svg" className={className} style={style} />
);

export const RoezanSMSNode: NodeDefinition = {
    type: 'automation-roezan-sms', category: 'communication', label: 'Roezan SMS',
    description: 'Send SMS and MMS, manage contacts, lists and tags, and automate broadcasts',
    keywords: ['text messages', 'messaging', 'broadcasts', 'Roezan'],
    Icon: RoezanSMSIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={RoezanSMSIcon} iconColor="" />),
};
