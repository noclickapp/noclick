import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SncfIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/sncf.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const SncfNode: NodeDefinition = {
    type: 'automation-sncf', category: 'industry', label: 'SNCF',
    description: 'Query SNCF Open Data datasets, records, facets and file exports',
    keywords: ['sncf', 'rail', 'train', 'open data'],
    Icon: SncfIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SncfIcon} iconColor="" />),
};
