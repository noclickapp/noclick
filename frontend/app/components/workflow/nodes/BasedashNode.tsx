// Basedash (AI-native BI / admin platform) automation node definition.
// Covers organizations, dashboards, charts, AI chats, automations, data sources,
// definitions (saved SQL), insights, MCP servers, members, groups, and skills.
// Authenticated with a Basedash API key (Bearer token).

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const BasedashIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/basedash.svg" alt="" className={className} style={style} {...props} />
    )
);
BasedashIcon.displayName = 'BasedashIcon';

const BasedashNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={BasedashIcon} iconColor="" />;
};

export const BasedashNode: NodeDefinition = {
    type: 'automation-basedash',
    label: 'Basedash',
    description: 'Basedash BI & admin automation',
    Icon: BasedashIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(BasedashNodeComponent),
};
