/** Catalog and canvas definition for Zoho CPaaS, formerly ZeptoMail.
 * Keeps channel actions and activity triggers discoverable under Communication. */
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ZohoCPaaSIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/zoho-cpaas-formerly-zeptomail.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const ZohoCPaaSNode: NodeDefinition = {
    type: 'automation-zoho-cpaas-formerly-zeptomail', category: 'communication',
    label: 'Zoho CPaaS - formerly ZeptoMail',
    description: 'Send transactional email, SMS, WhatsApp messages and voice calls; read logs and monitor activity',
    keywords: ['Zoho', 'ZeptoMail', 'CPaaS', 'transactional email', 'SMS', 'WhatsApp', 'voice'],
    Icon: ZohoCPaaSIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ZohoCPaaSIcon} iconColor="" />),
};
