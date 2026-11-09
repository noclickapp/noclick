// Zoho Cliq exposes chats, channels and text messages in the workflow catalog.
// The publisher's icon identifies the service consistently on the canvas.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ZohoCliqIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/zoho-cliq.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const ZohoCliqNode: NodeDefinition = {
    type: 'automation-zoho-cliq', category: 'communication', label: 'Zoho Cliq',
    description: 'Manage chats, channels, members and messages in Zoho Cliq',
    keywords: ['zoho', 'cliq', 'chat', 'team messaging'],
    Icon: ZohoCliqIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ZohoCliqIcon} iconColor="" />),
};
