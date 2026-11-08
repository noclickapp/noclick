import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const HlrLookupIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/hlr-lookup.png"
        alt=""
        aria-hidden="true"
        className={className}
        style={{ ...style, objectFit: 'contain' }}
    />
);

export const HlrLookupNode: NodeDefinition = {
    type: 'automation-hlr-lookup',
    category: 'communication',
    label: 'HLR Lookup',
    description:
        'Validate phone numbers, look up live status and carriers, and check credit balance',
    Icon: HlrLookupIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(function HlrLookupComponent(props: NodeProps) {
        return <AutomationNode {...props} Icon={HlrLookupIcon} iconColor="" />;
    }),
};
