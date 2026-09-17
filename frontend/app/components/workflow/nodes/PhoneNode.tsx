// Phone node: a phone number the workflow owns — bought inside NoClick as a
// credential, answered by the wired agent (on_call) and dialled from for it
// (place_call).
import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import { Phone } from 'lucide-react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const PhoneNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={Phone} iconColor="text-emerald-500" />;
};

export const PhoneNode: NodeDefinition = {
    type: 'automation-phone',
    label: 'Phone',
    description: 'A phone number your agent answers and calls from',
    keywords: ['phone number', 'call', 'voice', 'dial', 'answer calls'],
    Icon: Phone,
    iconColor: 'text-emerald-500',
    dimensions: DIMENSIONS,
    component: memo(PhoneNodeComponent),
};
