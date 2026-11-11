// Syncro's catalog and canvas definition. The icon is the publisher's favicon;
// its source and byte hash are recorded in the adjacent provenance sidecar.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const SyncroIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/syncro.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
SyncroIcon.displayName = 'SyncroIcon';

export const SyncroNode: NodeDefinition = {
    type: 'automation-syncro',
    label: 'Syncro',
    description: 'Manage customers, contacts, tickets and assets; read invoices and RMM alerts.',
    category: 'support',
    keywords: ['SyncroMSP', 'MSP', 'PSA', 'RMM', 'service desk'],
    Icon: SyncroIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SyncroIcon} iconColor="" />),
};
