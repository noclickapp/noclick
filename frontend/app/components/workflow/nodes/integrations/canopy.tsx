import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const CanopyIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/canopy.svg" dark="/icons/canopy-dark.svg" className={className} style={style} />
);

export const CanopyNode: NodeDefinition = {
    type: 'automation-canopy', category: 'finance-accounting', label: 'Canopy',
    description: 'Manage accounting clients, contacts, notes and tasks',
    keywords: ['accounting', 'tax', 'practice management', 'CRM'],
    Icon: CanopyIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CanopyIcon} iconColor="" />),
};
