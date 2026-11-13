import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const ClearBladeIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/clearblade.svg" dark="/icons/clearblade-dark.svg" className={className} style={style} />
);
export const ClearBladeNode: NodeDefinition = {
    type: 'automation-clearblade', category: 'developer-tools', label: 'ClearBlade',
    description: 'Automate IoT collection data, devices, code services and MQTT messages',
    Icon: ClearBladeIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ClearBladeIcon} iconColor="" />),
};
