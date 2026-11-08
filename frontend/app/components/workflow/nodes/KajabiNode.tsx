import { memo } from 'react';
import type { CSSProperties } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition } from './types';

// Official Kajabi brand asset; source and checksum are in asset-provenance.json.
const KajabiIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/kajabi.png"
        alt=""
        aria-hidden="true"
        className={className}
        style={{ ...style, objectFit: 'contain' }}
    />
);

export const KajabiNode: NodeDefinition = {
    type: 'automation-kajabi',
    category: 'courses',
    label: 'Kajabi',
    description:
        'Create and tag contacts, manage offer access, and sync customers and purchases',
    keywords: ['courses', 'memberships', 'contacts', 'offers', 'purchases'],
    Icon: KajabiIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={KajabiIcon} iconColor="" />
    )),
};
