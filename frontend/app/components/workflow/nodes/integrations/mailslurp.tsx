import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const MailslurpIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/mailslurp.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const MailslurpNode: NodeDefinition = {
    type: 'automation-mailslurp', category: 'developer-tools', label: 'MailSlurp',
    description: 'Create inboxes, send and receive email, and manage contacts',
    Icon: MailslurpIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MailslurpIcon} iconColor="" />),
};
