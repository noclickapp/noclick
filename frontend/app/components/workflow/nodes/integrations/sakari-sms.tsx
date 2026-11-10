import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SakariSMSIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/sakari-sms.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const SakariSMSNode: NodeDefinition = {
    type: 'automation-sakari-sms', category: 'communication', label: 'Sakari SMS',
    description: 'Send SMS and manage contacts, templates and conversations',
    keywords: ['Sakari', 'SMS', 'text messaging'],
    Icon: SakariSMSIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SakariSMSIcon} iconColor="" />),
};
