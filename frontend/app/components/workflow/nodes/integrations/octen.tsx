/** Octen canvas and integration catalog definition.
 * Uses the official provider icon and exposes search and research automation.
 */
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const OctenIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/octen.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const OctenNode: NodeDefinition = {
    type: 'automation-octen', label: 'Octen', category: 'content-research',
    description: 'Search the web, extract content, create embeddings and run AI research tasks',
    keywords: ['web search', 'news', 'images', 'video', 'embeddings', 'research'],
    Icon: OctenIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OctenIcon} iconColor="" />),
};
