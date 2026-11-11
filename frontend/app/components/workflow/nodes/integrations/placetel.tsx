import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const PlacetelIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/placetel.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const PlacetelNode: NodeDefinition = {
    type: 'automation-placetel', category: 'communication', label: 'Placetel', keywords: ['phone', 'voicemail', 'SIP', 'SMS', 'fax', 'incoming call', 'missed call', 'call answered', 'call ended', 'trigger'],
    description: 'Start workflows from call events and automate contacts, calls, SMS and faxes',
    Icon: PlacetelIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PlacetelIcon} iconColor="" />),
};
