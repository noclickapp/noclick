import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const OpenPolicyIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/openpolicy.svg" alt="" aria-hidden="true" className={className} style={{ ...style, objectFit: 'contain' }} />
);

export const OpenPolicyNode: NodeDefinition = {
    type: 'automation-openpolicy',
    label: 'Open Policy Agent',
    category: 'developer-tools',
    description: 'Evaluate policy decisions, manage Rego policies and data, query, compile and check OPA instances',
    keywords: ['OPA', 'Rego', 'authorization', 'policy engine'],
    Icon: OpenPolicyIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OpenPolicyIcon} iconColor="" />),
};
