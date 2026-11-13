// Walcu CRM's node definition makes the integration discoverable in the canvas and catalog.
// The icon is an unmodified publisher asset with provenance beside it.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const WalcuCRMIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => <ThemedBrandImg light="/icons/walcu-crm.svg" dark="/icons/walcu-crm-dark.svg" className={className} style={style} {...props} ref={ref} />,
);
WalcuCRMIcon.displayName = 'WalcuCRMIcon';

export const WalcuCRMNode: NodeDefinition = {
    type: 'automation-walcu-crm',
    label: 'Walcu CRM',
    description: 'Manage clients, sales leads, tasks, notes, vehicles and appointments; monitor CRM changes.',
    category: 'crm-sales',
    keywords: ['Walcu', 'dealership', 'automotive', 'sales leads'],
    Icon: WalcuCRMIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={WalcuCRMIcon} iconColor="" />),
};
