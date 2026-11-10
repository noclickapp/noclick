// Crelate uses the vendor wordmark in the discovered integration catalog.
// Forms and credentials come from its generated native schema.
import { forwardRef, type ImgHTMLAttributes } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const CrelateIcon = forwardRef<HTMLImageElement, ImgHTMLAttributes<HTMLImageElement>>(
    ({ style, ...props }, ref) => (
        <img {...props} ref={ref} src="/icons/crelate.svg" alt="" aria-hidden="true"
            style={{ ...style, objectFit: 'contain' }} />
    ),
);
CrelateIcon.displayName = 'CrelateIcon';

export const CrelateNode: NodeDefinition = {
    type: 'automation-crelate',
    label: 'Crelate',
    description: 'Recruiting CRM records, field and organization metadata',
    category: 'hr-recruiting',
    Icon: CrelateIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: (props: NodeProps) => <AutomationNode {...props} Icon={CrelateIcon} iconColor="" />,
};
