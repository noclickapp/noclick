// Snyk canvas and integration catalog definition. The shared automation renderer
// uses its generated schema for token connection and operation configuration.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SnykIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/snyk.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const SnykNode: NodeDefinition = {
    type: 'automation-snyk', category: 'developer-tools', label: 'Snyk',
    description: 'Manage Snyk projects, issues, ignores, tags and organization data',
    Icon: SnykIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SnykIcon} iconColor="" />),
};
