// BugSnag's definition is discovered from this integration file.
// The canvas component is loaded when a BugSnag node is used.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

const BugsnagIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/bugsnag-brand-vector.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

const BugsnagNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={BugsnagIcon} iconColor="" />
);

export const BugsnagNode: NodeDefinition = {
    type: 'automation-bugsnag',
    label: 'BugSnag',
    description: 'Monitor errors and manage projects in BugSnag',
    category: 'monitoring',
    Icon: BugsnagIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(BugsnagNodeComponent),
};
