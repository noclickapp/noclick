import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const SemanticScholarIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/semanticscholar.svg" dark="/icons/semanticscholar-dark.svg" className={className} style={style} />
);

export const SemanticScholarNode: NodeDefinition = {
    type: 'automation-semanticscholar', category: 'content-research', label: 'Semantic Scholar',
    description: 'Search papers and authors, retrieve citations, references and research metrics, and watch for new matching papers',
    Icon: SemanticScholarIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SemanticScholarIcon} iconColor="" />),
};
