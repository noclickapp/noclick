// Kantata OX project delivery tools and scheduled record triggers.
// The provider definition keeps the canvas and integration catalog in sync.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const KantataOXIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/kantataox.svg" className={className} style={style} />
);

export const KantataOXNode: NodeDefinition = {
    type: 'automation-kantataox', category: 'productivity', label: 'Kantata OX',
    description: 'Manage projects, tasks, time entries and activity posts; watch for new or updated records',
    keywords: ['Mavenlink', 'professional services', 'PSA', 'project management', 'timesheets'],
    Icon: KantataOXIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={KantataOXIcon} iconColor="" />),
};
