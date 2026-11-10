import { forwardRef, type ImgHTMLAttributes } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const InsightlyIcon = forwardRef<HTMLImageElement, ImgHTMLAttributes<HTMLImageElement>>(
    ({ style, ...props }, ref) => (
        <img {...props} ref={ref} src="/icons/insightly.svg" alt="" aria-hidden="true"
            style={{ ...style, objectFit: 'contain' }} />
    ),
);
InsightlyIcon.displayName = 'InsightlyIcon';

export const InsightlyNode: NodeDefinition = {
    type: 'automation-insightly',
    label: 'Insightly',
    description: 'Insightly CRM contacts, leads, opportunities, projects and tasks',
    category: 'crm-sales',
    Icon: InsightlyIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: (props: NodeProps) => <AutomationNode {...props} Icon={InsightlyIcon} iconColor="" />,
};
