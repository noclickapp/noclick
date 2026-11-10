// Displays the MaintainX integration in the catalog and workflow canvas.
// Configuration and credentials come from the generated backend schema.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const MaintainxIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <>
        <img src="/icons/maintainx.svg" alt="" aria-hidden="true" className={`${className ?? ''} dark:hidden`}
            style={{ ...style, objectFit: 'contain' }} />
        <img src="/icons/maintainx-dark.svg" alt="" aria-hidden="true" className={`${className ?? ''} hidden dark:block`}
            style={{ ...style, objectFit: 'contain' }} />
    </>
);

export const MaintainxNode: NodeDefinition = {
    type: 'automation-maintainx', category: 'industry', label: 'MaintainX',
    description: 'Automate work orders, assets, locations, parts and work requests',
    keywords: ['maintainx', 'cmms', 'maintenance', 'work orders', 'assets', 'inventory'],
    Icon: MaintainxIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MaintainxIcon} iconColor="" />),
};
