// TheHive security operations and polling triggers use the shared workflow node UI.
// This definition adds the integration to the canvas and public monitoring catalog.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const TheHiveIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/thehive.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const TheHiveNode: NodeDefinition = {
    type: 'automation-thehive', category: 'monitoring', label: 'TheHive',
    description: 'Automate security cases, alerts, observables and investigation tasks',
    Icon: TheHiveIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TheHiveIcon} iconColor="" />),
};
