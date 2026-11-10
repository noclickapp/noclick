/** Octen canvas and integration catalog definition.
 * Uses the official provider icon and exposes search and research automation.
 */
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const OctenIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/octen.svg" dark="/icons/octen-dark.svg" className={className} style={style} />
);

export const OctenNode: NodeDefinition = {
    type: 'automation-octen', label: 'Octen', category: 'content-research',
    description: 'Search the web, extract content, create embeddings and run AI research tasks',
    keywords: ['web search', 'news', 'images', 'video', 'embeddings', 'research'],
    Icon: OctenIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OctenIcon} iconColor="" />),
};
