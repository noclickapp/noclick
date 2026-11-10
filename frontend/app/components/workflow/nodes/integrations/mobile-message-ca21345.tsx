// Mobile Message sends Australian SMS and manages contacts and lists.
// The provider's official icon identifies its actions and real-time triggers in both catalogs.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const MobileMessageIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/mobile-message-ca21345.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const MobileMessageNode: NodeDefinition = {
    type: 'automation-mobile-message-ca21345', category: 'communication', label: 'Mobile Message',
    description: 'Send SMS, manage contacts and lists, and receive replies and delivery receipts',
    keywords: ['SMS', 'Australia', 'MobileMessage', 'text message', 'opt-out'],
    Icon: MobileMessageIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MobileMessageIcon} iconColor="" />),
};
