/** Instatus's catalog and canvas definition identifies status-page automation.
 * The shared automation component renders configuration from its generated schema.
 */
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const InstatusIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/instatus.svg" dark="/icons/instatus-dark.svg" className={className} style={style} />
);

export const InstatusNode: NodeDefinition = {
    type: 'automation-instatus', category: 'monitoring', label: 'Instatus',
    description: 'Manage status pages, components, incidents, maintenance and subscribers',
    keywords: ['status page', 'uptime', 'outage', 'incident', 'maintenance'],
    Icon: InstatusIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={InstatusIcon} iconColor="" />),
};
