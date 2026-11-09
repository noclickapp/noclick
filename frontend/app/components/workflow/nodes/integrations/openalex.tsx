import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const OpenAlexIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/openalex.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const OpenAlexNode: NodeDefinition = {
    type: 'automation-openalex', category: 'content-research', label: 'OpenAlex',
    description: 'Search scholarly works, authors, institutions, journals, funders and research topics',
    keywords: ['papers', 'research', 'citations', 'DOI', 'ORCID', 'scholarly'],
    Icon: OpenAlexIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OpenAlexIcon} iconColor="" />),
};
