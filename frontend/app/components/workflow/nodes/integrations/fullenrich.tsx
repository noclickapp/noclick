// FullEnrich's integration definition makes its generated operation schema discoverable.
// The official documentation favicon identifies the service on the canvas and in search.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const FullenrichIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/fullenrich.svg" dark="/icons/fullenrich-dark.svg" className={className} style={style} />
);

export const FullenrichNode: NodeDefinition = {
    type: 'automation-fullenrich', category: 'crm-sales', label: 'FullEnrich',
    description: 'Enrich contacts, reverse email lookup, search prospects and manage sub-accounts',
    keywords: ['fullenrich', 'email enrichment', 'phone enrichment', 'B2B', 'prospecting'],
    Icon: FullenrichIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={FullenrichIcon} iconColor="" />),
};
