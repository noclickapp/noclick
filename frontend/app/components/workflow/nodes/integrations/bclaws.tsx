// BC Laws offers public legislative browsing, search and document retrieval.
// This definition makes its credential-free CiviX operations available in the catalog.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const BCLawsIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/bclaws.svg" dark="/icons/bclaws-dark.svg" className={className} style={style} />
);

export const BCLawsNode: NodeDefinition = {
    type: 'automation-bclaws', label: 'BC Laws', category: 'content-research',
    description: 'Search British Columbia legislation and retrieve public laws in HTML or XML',
    keywords: ['British Columbia', 'legislation', 'statutes', 'regulations', 'CiviX'],
    Icon: BCLawsIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BCLawsIcon} iconColor="" />),
};
