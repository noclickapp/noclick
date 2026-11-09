/** Exposes Estimate Rocket in the workflow palette and integrations catalog.
 * Uses the publisher icon and industry category so contractor workflows can find it. */
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const EstimateRocketIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/converted-da-56088.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const EstimateRocketNode: NodeDefinition = {
    type: 'automation-converted-da-56088', category: 'industry', label: 'Estimate Rocket',
    description: 'Manage contractor clients, projects, invoices, payments, expenses and time entries',
    keywords: ['estimates', 'contractor', 'field service'],
    Icon: EstimateRocketIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={EstimateRocketIcon} iconColor="" />),
};
