import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const Smtp2GoIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/smtp2go.ico" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const Smtp2GoNode: NodeDefinition = {
    type: 'automation-smtp2go', category: 'communication', label: 'SMTP2GO',
    description: 'Send emails and manage sender domains, templates, suppressions and delivery reports',
    Icon: Smtp2GoIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={Smtp2GoIcon} iconColor="" />),
};
