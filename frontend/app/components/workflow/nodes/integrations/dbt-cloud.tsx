// Native dbt Administrative API metadata node and credential configuration.
// Uses the unchanged publisher SVG; warehouse execution is outside this node.
import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://www.getdbt.com/
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/dbt-cloud-brand-vector.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const DbtCloudNode: NodeDefinition = {
    type: 'automation-dbt-cloud', category: 'analytics-bi', label: 'dbt Cloud',
    description: 'Read account, project, environment, job and run metadata; summarize JSON artifacts',
    Icon: OfficialBrandIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />),
};
