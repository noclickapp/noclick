import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Official Avaza homepage logo.
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/avaza.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

const AvazaNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />;
export const AvazaNode: NodeDefinition = {
    type: 'automation-avaza', category: 'productivity', label: 'Avaza',
    description: 'Avaza account-bound company, project, task and time metadata reads',
    Icon: OfficialBrandIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: AvazaNodeComponent,
};
