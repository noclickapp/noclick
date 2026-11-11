import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const OpenStatesIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <>
        <img src="/icons/openstates.svg" alt="" aria-hidden="true" className={`${className ?? ''} dark:hidden`} style={style} />
        <img src="/icons/openstates-dark.svg" alt="" aria-hidden="true" className={`${className ?? ''} hidden dark:block`} style={style} />
    </>
);

export const OpenStatesNode: NodeDefinition = {
    type: 'automation-openstates', label: 'Open States', category: 'content-research',
    description: 'Research state bills, legislators, jurisdictions, committees and events; monitor bill updates',
    keywords: ['Open States API v3', 'openstates', 'legislation', 'government', 'state legislature'],
    Icon: OpenStatesIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 52 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OpenStatesIcon} iconColor="" />),
};
