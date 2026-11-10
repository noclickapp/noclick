// Hubflo's catalog and canvas definition uses the generated backend operation forms.
// Its official brand icon identifies the connected client portal service.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const HubfloIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/hubflo.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);

export const HubfloNode: NodeDefinition = {
    type: 'automation-hubflo', category: 'crm-sales', label: 'Hubflo',
    description: 'Manage contacts, companies, tasks, projects and client workspaces; receive signed creation events.',
    Icon: HubfloIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={HubfloIcon} iconColor="" />),
};
