import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const OpenCageIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/opencage.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const OpenCageNode: NodeDefinition = {
    type: 'automation-opencage', category: 'developer-tools', label: 'OpenCage',
    description: 'Geocode addresses, reverse coordinates and export GeoJSON',
    Icon: OpenCageIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OpenCageIcon} iconColor="" />),
};
