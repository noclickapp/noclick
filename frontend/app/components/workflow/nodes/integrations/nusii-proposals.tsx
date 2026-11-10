import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const NusiiIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/nusii-proposals.svg"
        alt=""
        aria-hidden="true"
        className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties}
    />
);

export const NusiiProposalsNode: NodeDefinition = {
    type: 'automation-nusii-proposals',
    label: 'Nusii Proposals',
    category: 'documents',
    description:
        'Create and send proposals, manage clients, sections and pricing',
    keywords: ['nusii', 'proposals', 'quotes'],
    Icon: NusiiIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={NusiiIcon} iconColor="" />
    )),
};
