// US Global Mail's discovered definition exposes mailbox actions and polling triggers.
// The unmodified publisher logo is reviewed in its adjacent provenance sidecar.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const USGlobalMailIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/us-global-mail.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const USGlobalMailNode: NodeDefinition = {
    type: 'automation-us-global-mail',
    label: 'US Global Mail',
    category: 'communication',
    description: 'Manage mail, request scans, track shipments and organize folders',
    keywords: ['USGM', 'virtual mailbox', 'postal mail', 'scans', 'mail forwarding'],
    Icon: USGlobalMailIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={USGlobalMailIcon} iconColor="" />),
};
