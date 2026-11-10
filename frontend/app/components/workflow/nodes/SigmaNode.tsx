// Sigma Computing BI automation node definition.
// Provides workflow integration with the Sigma Computing v2 REST API
// (workbooks, members, teams, connections, workspaces, catalog).

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const SigmaIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>((props, ref) => (
    <ThemedBrandImg ref={ref} light="/icons/sigma-light.svg" dark="/icons/sigma.svg" {...props} />
));
SigmaIcon.displayName = 'SigmaIcon';

const SigmaNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={SigmaIcon} iconColor="" />;
};

export const SigmaNode: NodeDefinition = {
    type: 'automation-sigma',
    label: 'Sigma Computing',
    description: 'Sigma Computing BI automation',
    Icon: SigmaIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(SigmaNodeComponent),
};
