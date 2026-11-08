/** Instatus's catalog and canvas definition identifies status-page automation.
 * The shared automation component renders configuration from its generated schema.
 */
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const InstatusIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/instatus.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const InstatusNode: NodeDefinition = {
    type: 'automation-instatus', category: 'monitoring', label: 'Instatus',
    description: 'Manage status pages, components, incidents, maintenance and subscribers',
    keywords: ['status page', 'uptime', 'outage', 'incident', 'maintenance'],
    Icon: InstatusIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={InstatusIcon} iconColor="" />),
};
