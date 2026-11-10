// SmartEmailing's canvas and integration catalog definition.
// The shared automation component renders the generated operation and credential forms.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SmartEmailingIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/smartemailing.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const SmartEmailingNode: NodeDefinition = {
    type: 'automation-smartemailing',
    label: 'SmartEmailing',
    category: 'marketing',
    description: 'Manage contacts, lists, custom fields, email templates and automation events',
    keywords: ['email marketing', 'newsletter', 'transactional email', 'contact import'],
    Icon: SmartEmailingIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SmartEmailingIcon} iconColor="" />),
};
