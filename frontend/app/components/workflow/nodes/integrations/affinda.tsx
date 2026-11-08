import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const AffindaIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/affinda.png"
        alt=""
        aria-hidden="true"
        className={className}
        style={
            {
                ...style,
                '--brand-invert': 0,
                objectFit: 'contain',
            } as CSSProperties
        }
    />
);

export const AffindaNode: NodeDefinition = {
    type: 'automation-affinda',
    category: 'documents',
    label: 'Affinda',
    description:
        'Parse documents, manage tags and read workspaces, collections and usage',
    Icon: AffindaIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(function AffindaCanvas(props: NodeProps) {
        return <AutomationNode {...props} Icon={AffindaIcon} iconColor="" />;
    }),
};
