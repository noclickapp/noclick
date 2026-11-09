import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const MailerLiteClassicIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/mailerlite-classic.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const MailerLiteClassicNode: NodeDefinition = {
    type: 'automation-mailerlite-classic', category: 'marketing', label: 'MailerLite Classic',
    description: 'Manage Classic subscribers, groups and custom fields; read campaigns and stats',
    Icon: MailerLiteClassicIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MailerLiteClassicIcon} iconColor="" />),
};
