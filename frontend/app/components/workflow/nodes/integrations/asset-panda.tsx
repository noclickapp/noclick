// Asset Panda's canvas definition is discovered from its integration filename.
// Its component loads only when an Asset Panda node appears on the canvas.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

// Unmodified Asset Panda logo from its official website; see the icon's provenance sidecar.
const AssetPandaIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/asset-panda.svg"
        alt=""
        aria-hidden="true"
        className={className}
        style={{ ...style, objectFit: 'contain' }}
    />
);

const AssetPandaNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={AssetPandaIcon} iconColor="" />
);

export const AssetPandaNode: NodeDefinition = {
    type: 'automation-asset-panda',
    label: 'Asset Panda',
    description: 'Read account, module, collection, column and record metadata',
    category: 'industry',
    Icon: AssetPandaIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(AssetPandaNodeComponent),
};
