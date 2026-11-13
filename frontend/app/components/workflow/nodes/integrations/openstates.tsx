import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const OpenStatesIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/openstates.svg" dark="/icons/openstates-dark.svg" className={className} style={style} />
);

export const OpenStatesNode: NodeDefinition = {
    type: 'automation-openstates', label: 'Open States', category: 'content-research',
    description: 'Research state bills, legislators, jurisdictions, committees and events; monitor bill updates',
    keywords: ['Open States API v3', 'openstates', 'legislation', 'government', 'state legislature'],
    Icon: OpenStatesIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 52 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OpenStatesIcon} iconColor="" />),
};
