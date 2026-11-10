import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const InstapaperIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/instapaper.svg" dark="/icons/instapaper-dark.svg" className={className} style={style} />
);

export const InstapaperNode: NodeDefinition = {
    type: 'automation-instapaper', category: 'content-research', label: 'Instapaper',
    description: 'Save, organize, tag and read Instapaper bookmarks',
    Icon: InstapaperIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={InstapaperIcon} iconColor="" />),
};
