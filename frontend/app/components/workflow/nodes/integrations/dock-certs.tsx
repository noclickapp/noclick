import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const DockCertsIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/dock-certs.png"
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

export const DockCertsNode: NodeDefinition = {
    type: 'automation-dock-certs',
    category: 'documents',
    label: 'Dock Certs',
    keywords: ['Truvera', 'verifiable credentials', 'decentralized identity'],
    description:
        'Issue and verify credentials; manage DIDs, schemas, profiles and proof requests',
    Icon: DockCertsIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(function DockCertsCanvasNode(props: NodeProps) {
        return <AutomationNode {...props} Icon={DockCertsIcon} iconColor="" />;
    }),
};
