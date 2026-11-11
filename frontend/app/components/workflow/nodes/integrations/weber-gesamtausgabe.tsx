// Displays WeGA's public scholarly API in the node palette and workflow canvas.
// The provider's own pinned-tab mark is paired for light and dark surfaces.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const WegaIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <>
        <img src="/icons/weber-gesamtausgabe.svg" alt="" aria-hidden="true" className={`${className ?? ''} dark:hidden`} style={style} />
        <img src="/icons/weber-gesamtausgabe-dark.svg" alt="" aria-hidden="true" className={`${className ?? ''} hidden dark:block`} style={style} />
    </>
);

export const WeberGesamtausgabeNode: NodeDefinition = {
    type: 'automation-weber-gesamtausgabe',
    label: 'WeGA API',
    category: 'content-research',
    description: 'Search Weber documents, authors, repositories, historical events and XML samples',
    keywords: ['WeGA', 'Weber', 'Carl Maria von Weber', 'Gesamtausgabe', 'music', 'digital edition', 'TEI'],
    Icon: WegaIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={WegaIcon} iconColor="" />),
};
