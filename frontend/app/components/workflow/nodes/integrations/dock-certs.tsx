import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const DockCertsIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <ThemedBrandImg light="/icons/dock-certs.svg" dark="/icons/dock-certs-dark.svg" className={className} style={style} />
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
