import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const EmaillistverifyIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/emaillistverify.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const EmaillistverifyNode: NodeDefinition = {
    type: 'automation-emaillistverify', label: 'EmailListVerify',
    description: 'Verify emails, manage verification jobs and test inbox placement',
    Icon: EmaillistverifyIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={EmaillistverifyIcon} iconColor="" />),
};
