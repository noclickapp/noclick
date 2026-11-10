import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const KeycloakIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <>
        <img src="/icons/keycloak.svg" alt="" aria-hidden="true" className={`${className ?? ''} dark:hidden`} style={{ ...style, objectFit: 'contain' }} />
        <img src="/icons/keycloak-dark.svg" alt="" aria-hidden="true" className={`${className ?? ''} hidden dark:block`} style={{ ...style, objectFit: 'contain' }} />
    </>
);

export const KeycloakNode: NodeDefinition = {
    type: 'automation-keycloak', category: 'developer-tools', label: 'Keycloak',
    description: 'Manage realm users, groups, role mappings, clients and sessions; watch for new users',
    Icon: KeycloakIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={KeycloakIcon} iconColor="" />),
};
