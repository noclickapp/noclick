import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
const RedirectPizzaIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/redirect-pizza.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);
export const RedirectPizzaNode: NodeDefinition = {
    type: 'automation-redirect-pizza', category: 'developer-tools', label: 'Redirect Pizza',
    description: 'Manage URL redirects, email forwarding, domains and redirect analytics',
    keywords: ['redirect.pizza', 'URL forwarding', 'DNS'],
    Icon: RedirectPizzaIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={RedirectPizzaIcon} iconColor="" />),
};
