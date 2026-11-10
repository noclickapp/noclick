// Registers Turbot Pipes in the integration catalog and workflow canvas.
// The provider's official icon identifies the workspace automation node.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const TurbotPipesIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/turbot-pipes.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const TurbotPipesNode: NodeDefinition = {
    type: 'automation-turbot-pipes', category: 'developer-tools', label: 'Turbot Pipes',
    description: 'Query cloud data and manage organization workspaces, connections and snapshots',
    keywords: ['Steampipe', 'SQL', 'cloud', 'DevOps'],
    Icon: TurbotPipesIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TurbotPipesIcon} iconColor="" />),
};
