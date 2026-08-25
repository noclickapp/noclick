// MongoDB Atlas Admin API node definition.
// Provides workflow integration with the Atlas Admin API v2 for managing clusters,
// backups, users, network, alerts, billing, and all other Atlas control-plane resources.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 52 };

const AtlasAdminIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/atlas-admin.svg"
        alt=""
        className={className}
        style={style}
        {...props}
    />
));
AtlasAdminIcon.displayName = 'AtlasAdminIcon';

const AtlasAdminNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={AtlasAdminIcon} iconColor="" />;
};

export const AtlasAdminNode: NodeDefinition = {
    type: 'automation-atlas-admin',
    label: 'Atlas Admin',
    description: 'MongoDB Atlas cluster management, backups, users, network, alerts, billing',
    Icon: AtlasAdminIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(AtlasAdminNodeComponent),
    keywords: [
        'mongodb', 'atlas', 'admin', 'cluster', 'backup', 'database', 'cloud',
        'snapshot', 'restore', 'users', 'network', 'peering', 'alerts', 'billing',
        'monitoring', 'performance', 'indexes', 'streams', 'federation', 'serverless',
    ],
};
