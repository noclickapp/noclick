import { memo, forwardRef } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const FungeneratorsIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/fungenerators.svg" alt="" className={className}
            style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
FungeneratorsIcon.displayName = 'FungeneratorsIcon';

export const FungeneratorsNode: NodeDefinition = {
    type: 'automation-fungenerators',
    label: 'UUID Generation API',
    description: 'Generate UUIDs and check UUID validity and version with Fun Generators',
    category: 'developer-tools',
    keywords: ['Fun Generators', 'fungenerators', 'UUID', 'GUID', 'identifier'],
    Icon: FungeneratorsIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={FungeneratorsIcon} iconColor="" />),
};
