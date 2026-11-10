import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ObonoIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/obono.svg" alt="" aria-hidden="true" className={className} style={style} />
);

export const ObonoNode: NodeDefinition = {
    type: 'automation-obono',
    label: 'obono',
    category: 'finance-accounting',
    description: 'Sign RKSV receipts, monitor new receipts, close periods and export cash register records',
    keywords: ['RKSV', 'cash register', 'Registrierkasse', 'receipts', 'Austria'],
    Icon: ObonoIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ObonoIcon} iconColor="" />),
};
