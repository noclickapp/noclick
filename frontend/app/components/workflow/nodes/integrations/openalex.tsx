import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const OpenAlexIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/openalex.svg" dark="/icons/openalex-dark.svg" className={className} style={style} />
);

export const OpenAlexNode: NodeDefinition = {
    type: 'automation-openalex', category: 'content-research', label: 'OpenAlex',
    description: 'Search scholarly data and watch the latest 100 matching works for new records or updates (Member+ or Partner)',
    keywords: ['papers', 'research', 'citations', 'DOI', 'ORCID', 'scholarly'],
    Icon: OpenAlexIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OpenAlexIcon} iconColor="" />),
};
