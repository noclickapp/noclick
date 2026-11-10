import { memo, type CSSProperties } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

// Unmodified Okta Aura Stack from the official newsroom's logo archive.
const OktaIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/okta-brand.svg" dark="/icons/okta-brand-dark.svg" className={className} style={{ ...style, objectFit: 'contain' }} />
);

export const OktaNode: NodeDefinition = {
    type: 'automation-okta',
    label: 'Okta',
    description: 'Manage Okta users, groups, app assignments and lifecycle',
    category: 'developer-tools',
    keywords: ['identity', 'access', 'onboarding', 'offboarding', 'SSO'],
    Icon: OktaIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OktaIcon} iconColor="" />),
};
