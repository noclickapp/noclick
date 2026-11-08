// Registers Wild Apricot in the workflow catalog and canvas through discovery.
// The shared automation node renders its generated member API configuration.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const WildApricotIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/wild-apricot.webp" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const WildApricotNode: NodeDefinition = {
    type: 'automation-wild-apricot', label: 'Wild Apricot',
    description: 'Manage member profiles and event registrations; read contacts, events, invoices and payments',
    Icon: WildApricotIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={WildApricotIcon} iconColor="" />),
};
