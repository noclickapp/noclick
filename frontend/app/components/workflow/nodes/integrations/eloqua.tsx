import { memo } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Oracle wordmark from its public documentation stylesheet.
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/eloqua.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

const Component = (props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />;
export const EloquaNode: NodeDefinition = {
    type: 'automation-eloqua', category: 'marketing', label: 'Oracle Eloqua', description: 'Authenticated site and user, contact/account metadata and custom object management.',
    Icon: OfficialBrandIcon, iconColor: '', dimensions: { width: 110, height: 90, iconSize: 48 }, component: memo(Component),
};
