// Clerk.io canvas definition, discovered by integration filename.
// The component displays the provider brand and shared automation controls.
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

// Official brand artwork from https://clerk.io/.
const ClerkIOIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/clerk-io-brand-vector.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

const ClerkIONodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={ClerkIOIcon} iconColor="" />;

export const ClerkIONode: NodeDefinition = {
    type: 'automation-clerk-io',
    label: 'Clerk.io',
    description: 'Manage ecommerce catalogs and retrieve product recommendations',
    category: 'ecommerce',
    Icon: ClerkIOIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: ClerkIONodeComponent,
};
