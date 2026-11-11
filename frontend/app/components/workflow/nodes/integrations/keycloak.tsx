import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const KeycloakIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/keycloak.svg" dark="/icons/keycloak-dark.svg" className={className} style={{ ...style, objectFit: 'contain' }} />
);

export const KeycloakNode: NodeDefinition = {
    type: 'automation-keycloak', category: 'developer-tools', label: 'Keycloak',
    description: 'Manage realm users, groups, role mappings, clients and sessions; watch for new users',
    Icon: KeycloakIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={KeycloakIcon} iconColor="" />),
};
