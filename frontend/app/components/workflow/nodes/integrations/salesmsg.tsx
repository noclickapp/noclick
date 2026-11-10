import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const SalesmsgIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg light="/icons/salesmsg.svg" dark="/icons/salesmsg-dark.svg" className={className} style={style} {...props} ref={ref} />
    ),
);
SalesmsgIcon.displayName = 'SalesmsgIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const SalesmsgNode: NodeDefinition = {
    type: 'automation-salesmsg',
    label: 'Salesmsg',
    description: 'Send SMS and manage contacts, conversations, tags and inboxes',
    category: 'communication',
    keywords: ['SalesMessage', 'SMS', 'text messaging'],
    Icon: SalesmsgIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SalesmsgIcon} iconColor="" />),
};
