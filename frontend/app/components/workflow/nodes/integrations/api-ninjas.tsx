import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const ApiNinjasIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/api-ninjas.png" dark="/icons/api-ninjas-dark.png" className={className} style={style} />
);

export const ApiNinjasNode: NodeDefinition = {
    type: 'automation-api-ninjas', category: 'developer-tools', label: 'API Ninjas',
    description: 'Validate contacts, enrich locations, query finance and analyze text',
    keywords: ['Api Ninjas', 'api_ninjas', 'email validation', 'geocoding', 'currency', 'text similarity'],
    Icon: ApiNinjasIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ApiNinjasIcon} iconColor="" />),
};
