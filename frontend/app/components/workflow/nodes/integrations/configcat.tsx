import { memo } from 'react';
import type { CSSProperties } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

const ConfigCatIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/configcat.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

const ConfigCatNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={ConfigCatIcon} iconColor="" />
);

export const ConfigCatNode: NodeDefinition = {
    type: 'automation-configcat',
    label: 'ConfigCat',
    description: 'Manage ConfigCat feature flags, products, configurations and environments',
    keywords: ['feature flags', 'settings', 'configuration', 'environments'],
    Icon: ConfigCatIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(ConfigCatNodeComponent),
};
