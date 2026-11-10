// HigherGov's discoverable workflow definition uses the official provider mark.
// Operations and credential fields come from the generated backend schema.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const HigherGovIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/highergov.svg" dark="/icons/highergov-dark.svg" className={className} style={style} />
);

export const HigherGovNode: NodeDefinition = {
    type: 'automation-highergov', category: 'crm-sales', label: 'HigherGov',
    description: 'Read government opportunities, awards, contractors and your pursuits',
    keywords: ['Highergov', 'government contracting', 'federal grants', 'procurement'],
    Icon: HigherGovIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={HigherGovIcon} iconColor="" />),
};
