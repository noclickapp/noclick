import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
const ClearBladeIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/clearblade.svg" alt="" aria-hidden="true" className={className} style={{ ...style, objectFit: 'contain' }} />
);
export const ClearBladeNode: NodeDefinition = {
    type: 'automation-clearblade', category: 'developer-tools', label: 'ClearBlade',
    description: 'Automate IoT collection data, devices, code services and MQTT messages',
    Icon: ClearBladeIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ClearBladeIcon} iconColor="" />),
};
