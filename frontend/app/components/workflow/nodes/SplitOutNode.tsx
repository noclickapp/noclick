// Split Out node — turns an array (or an array field on an object) into one
// item per element. A control-flow/data node with no credentials;
// pair it with an Iteration node to process each item. Added so users have a
// dedicated Split Out step instead of a Filter operation.

import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import { Split, type LucideProps } from 'lucide-react';
import AutomationNode from './base/AutomationNode';
import type { NodeDefinition } from './types';

const DIMENSIONS = { width: 110, height: 110, iconSize: 56 };

// lucide's Split rotated 90° clockwise.
const SplitIcon = (props: LucideProps) => (
    <Split {...props} className={['rotate-90', props.className].filter(Boolean).join(' ')} />
);

const SplitOutNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={SplitIcon} iconColor="text-cyan-400" />;
};

export const SplitOutNode: NodeDefinition = {
    type: 'split-out',
    label: 'Split Out',
    description: 'Split an array into separate items',
    Icon: SplitIcon,
    iconColor: 'text-cyan-400',
    dimensions: DIMENSIONS,
    component: memo(SplitOutNodeComponent),
};
