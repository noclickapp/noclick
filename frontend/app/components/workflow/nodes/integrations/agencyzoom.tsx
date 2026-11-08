// AgencyZoom exposes CRM actions in both the workflow canvas and action catalog.
// Its official brand icon identifies the connected insurance agency service.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const AgencyZoomIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/agencyzoom.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const AgencyZoomNode: NodeDefinition = {
    type: 'automation-agencyzoom', category: 'industry', label: 'AgencyZoom',
    description: 'Manage insurance leads, customers, policies, notes and tasks',
    keywords: ['agencyzoom', 'agency zoom', 'insurance', 'CRM', 'sales'],
    Icon: AgencyZoomIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AgencyZoomIcon} iconColor="" />),
};
