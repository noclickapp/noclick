import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const GoodapiPlantTreesIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/goodapi-plant-trees.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const GoodapiPlantTreesNode: NodeDefinition = {
    type: 'automation-goodapi-plant-trees', category: 'nonprofit', label: 'Goodapi Plant Trees',
    description: 'Plant trees, recover plastic, record donations and track impact',
    Icon: GoodapiPlantTreesIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={GoodapiPlantTreesIcon} iconColor="" />),
};
