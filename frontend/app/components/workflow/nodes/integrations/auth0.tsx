import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const Auth0Icon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/auth0.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const Auth0Node: NodeDefinition = {
    type: 'automation-auth0',
    label: 'Auth0',
    description: 'Manage Auth0 users, roles, organizations and logs',
    category: 'developer-tools',
    keywords: ['identity', 'access management', 'tenant', 'authentication'],
    Icon: Auth0Icon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={Auth0Icon} iconColor="" />),
};
