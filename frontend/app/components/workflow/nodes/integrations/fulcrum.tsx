// Fulcrum's native form and field-record node uses the official published logo.
// Its organization token and form-dependent configuration come from the native schema.
import { memo } from 'react';
import { type NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { type NodeDefinition } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://fulcrumapp.com
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/fulcrum-brand-vector.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

const FulcrumNodeComponent = (props: NodeProps) =>
    <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />;

export const FulcrumNode: NodeDefinition = {
    type: 'automation-fulcrum',
    label: 'Fulcrum',
    description: 'Read forms and manage field records, projects and choice lists',
    category: 'industry',
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 60 },
    component: memo(FulcrumNodeComponent),
};
