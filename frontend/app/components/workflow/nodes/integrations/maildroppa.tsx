import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const MaildroppaIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/maildroppa.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const MaildroppaNode: NodeDefinition = {
    type: 'automation-maildroppa', category: 'marketing', label: 'Maildroppa',
    description: 'Manage subscribers, tags, topics, fields and segments',
    Icon: MaildroppaIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MaildroppaIcon} iconColor="" />),
};
