// Apiverve exposes validation, lookups and generated documents through one API key.
// This definition makes the self-registering node available in both palettes.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ApiverveIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/apiverve.png" alt="" aria-hidden="true" className={className} style={{ ...style, objectFit: 'contain' }} />
);
export const ApiverveNode: NodeDefinition = {
    type: 'automation-apiverve', category: 'developer-tools', label: 'Apiverve',
    description: 'Validate emails and phone numbers, look up domains, convert currencies and generate documents and images',
    Icon: ApiverveIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ApiverveIcon} iconColor="" />),
};
