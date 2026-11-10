import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const CloudTalkIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/cloudtalk.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const CloudTalkNode: NodeDefinition = {
    type: 'automation-cloudtalk', category: 'communication', label: 'CloudTalk',
    description: 'Manage contacts, tags and notes, send SMS, place calls and read call history',
    Icon: CloudTalkIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CloudTalkIcon} iconColor="" />),
};
