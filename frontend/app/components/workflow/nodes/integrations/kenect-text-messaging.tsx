// Kenect's messaging integration is discovered from this definition.
// Its official brand icon identifies the service in the workflow and catalog.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const KenectIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/kenect-text-messaging.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const KenectTextMessagingNode: NodeDefinition = {
    type: 'automation-kenect-text-messaging', category: 'communication', label: 'Kenect Text Messaging',
    description: 'Send texts and review requests, sync contacts, and read conversations and leads',
    keywords: ['Kenect', 'SMS', 'text messaging', 'reviews'],
    Icon: KenectIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={KenectIcon} iconColor="" />),
};
