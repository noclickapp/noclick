// Adafruit IO's native automation node is discovered through this definition.
// The official publisher icon is reviewed in the sidecar beside the asset.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const AdafruitIOIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/adafruit-io.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);

export const AdafruitIONode: NodeDefinition = {
    type: 'automation-adafruit-io', category: 'developer-tools', label: 'Adafruit IO',
    description: 'Read and write IoT feed data, manage feeds and organize groups',
    keywords: ['adafruit', 'iot', 'sensors', 'telemetry'],
    Icon: AdafruitIOIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AdafruitIOIcon} iconColor="" />),
};
