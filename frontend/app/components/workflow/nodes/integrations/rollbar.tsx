// Rollbar's definition is discovered from this integration file.
// The canvas component is loaded when a Rollbar node is used.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

const RollbarIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/rollbar-brand-vector.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

const RollbarNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={RollbarIcon} iconColor="" />
);

export const RollbarNode: NodeDefinition = {
    type: 'automation-rollbar',
    label: 'Rollbar',
    category: 'monitoring',
    description: 'Monitor errors, projects, teams, and deploys in Rollbar',
    Icon: RollbarIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(RollbarNodeComponent),
};
