import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const BulkSMSComIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/bulksmscom.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const BulkSMSComNode: NodeDefinition = {
    type: 'automation-bulksmscom', category: 'communication', label: 'BulkSMS.com',
    description: 'Send SMS, read messages and account balance, manage blocked numbers and webhooks',
    Icon: BulkSMSComIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BulkSMSComIcon} iconColor="" />),
};
