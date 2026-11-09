// Practice Better automates client records, bookings, programs, tags and invoices.
// This definition exposes the generated configuration and the official provider mark.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const PracticeBetterIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/practice-better.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const PracticeBetterNode: NodeDefinition = {
    type: 'automation-practice-better', category: 'industry', label: 'Practice Better',
    description: 'Manage clients, book sessions, enroll clients in programs, and read invoices',
    Icon: PracticeBetterIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PracticeBetterIcon} iconColor="" />),
};
