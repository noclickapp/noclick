import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const EterminIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/etermin.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const EterminNode: NodeDefinition = {
    type: 'automation-etermin', category: 'bookings', label: 'eTermin',
    description: 'Manage appointments, contacts, services, calendars, availability and absences',
    Icon: EterminIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={EterminIcon} iconColor="" />),
};
