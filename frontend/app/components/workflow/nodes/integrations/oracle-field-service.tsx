// Field Service metadata and bucket activity actions use the native automation editor.
// The unchanged Oracle corporate mark comes from the official documentation stylesheet.
import { memo } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Unmodified Oracle corporate mark from the official documentation stylesheet.
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/oracle-field-service.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const OracleFieldServiceNode: NodeDefinition = {
    type: 'automation-oracle-field-service', category: 'industry', label: 'Oracle Field Service',
    description: 'Resource, activity, property, type and capacity metadata with bucket activity management',
    Icon: OfficialBrandIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />),
};
