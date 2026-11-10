import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const KadoaIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/kadoa.svg" dark="/icons/kadoa-dark.svg" className={className} style={style} />
);

export const KadoaNode: NodeDefinition = {
    type: 'automation-kadoa', category: 'content-research', label: 'Kadoa',
    description: 'Extract website data, manage workflows and reusable extraction schemas',
    keywords: ['scraping', 'web extraction', 'monitoring'],
    Icon: KadoaIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={KadoaIcon} iconColor="" />),
};
