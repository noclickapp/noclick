// Daylite CRM automation node and official service icon.
// The definition makes the integration discoverable in the canvas and catalog.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const DayliteIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/daylite.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const DayliteNode: NodeDefinition = {
    type: 'automation-daylite', category: 'crm-sales', label: 'Daylite',
    description: 'Manage contacts, companies, tasks, notes, projects and opportunities',
    Icon: DayliteIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={DayliteIcon} iconColor="" />),
};
