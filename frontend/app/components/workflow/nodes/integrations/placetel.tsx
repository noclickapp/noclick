import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const PlacetelIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/placetel.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const PlacetelNode: NodeDefinition = {
    type: 'automation-placetel', category: 'communication', label: 'Placetel', keywords: ['phone', 'voicemail', 'SIP', 'SMS', 'fax'],
    description: 'Automate contacts, calls, SMS, faxes, phone numbers and call groups',
    Icon: PlacetelIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PlacetelIcon} iconColor="" />),
};
