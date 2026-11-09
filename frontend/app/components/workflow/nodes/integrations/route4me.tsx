// Route4Me uses the shared schema-driven workflow node. Its official brand mark identifies the service.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const Route4MeIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/route4me.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const Route4MeNode: NodeDefinition = {
    type: 'automation-route4me', category: 'industry', label: 'Route4Me',
    description: 'Manage address-book contacts, vehicles and delivery territories',
    Icon: Route4MeIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={Route4MeIcon} iconColor="" />),
};
