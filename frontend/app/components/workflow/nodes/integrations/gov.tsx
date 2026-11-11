import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const GovIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/gov.svg" dark="/icons/gov-dark.svg" className={className} style={style} />
);

export const GovNode: NodeDefinition = {
    type: 'automation-gov', category: 'content-research', label: 'BC Data Catalogue',
    description: 'Search British Columbia datasets, resources and organizations, and watch dataset metadata changes',
    keywords: ['BC Data Catalogue API', 'DataBC', 'CKAN', 'British Columbia', 'open data'],
    Icon: GovIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={GovIcon} iconColor="" />),
};
