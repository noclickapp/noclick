import { memo, type CSSProperties } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

const RingCentralIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/ringcentral.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

const RingCentralNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={RingCentralIcon} iconColor="" />
);

export const RingCentralNode: NodeDefinition = {
    type: 'automation-ringcentral',
    label: 'RingCentral',
    description: 'Calls, SMS, faxes, call logs and contacts',
    category: 'communication',
    Icon: RingCentralIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(RingCentralNodeComponent),
};
