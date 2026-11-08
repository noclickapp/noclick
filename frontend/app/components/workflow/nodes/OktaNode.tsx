import { memo, type CSSProperties } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition } from './types';

// Unmodified Okta Aura Stack from the official newsroom's logo archive.
const OktaIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/okta-brand.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
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
