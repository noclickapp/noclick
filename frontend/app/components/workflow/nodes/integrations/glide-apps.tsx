import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const GlideIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/glide-apps.svg" dark="/icons/glide-apps-dark.svg" className={className} style={style} />
);

export const GlideAppsNode: NodeDefinition = {
    type: 'automation-glide-apps', category: 'databases-storage', label: 'Glide',
    description: 'Read and write Glide Big Tables, import data, and manage rows, jobs and stashes',
    keywords: ['Glide Apps', 'Big Tables', 'no code'],
    Icon: GlideIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={GlideIcon} iconColor="" />),
};
