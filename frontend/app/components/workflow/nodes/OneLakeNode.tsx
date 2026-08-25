// OneLake (Microsoft Fabric) automation node definition.
// Provides workflow integration with the OneLake REST APIs: filesystem
// (ADLS Gen2 / DFS), table metadata (Iceberg / Delta), and shortcut/settings
// management via the Fabric Core REST API. Authenticated with Microsoft OAuth.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const OneLakeIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img ref={ref} src="/icons/onelake.svg" alt="" className={className} style={style} {...props} />
));
OneLakeIcon.displayName = 'OneLakeIcon';

const OneLakeNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={OneLakeIcon} iconColor="" />;
};

export const OneLakeNode: NodeDefinition = {
    type: 'automation-onelake',
    label: 'OneLake',
    description: 'Microsoft Fabric OneLake automation',
    Icon: OneLakeIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(OneLakeNodeComponent),
};
