import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const CaspioIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/caspio.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
CaspioIcon.displayName = 'CaspioIcon';

export const CaspioNode: NodeDefinition = {
    type: 'automation-caspio',
    label: 'Caspio',
    description: 'Query and write table records, inspect views and run tasks',
    category: 'databases-storage',
    keywords: ['database', 'records', 'tables', 'views', 'low code'],
    Icon: CaspioIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CaspioIcon} iconColor="" />),
};
