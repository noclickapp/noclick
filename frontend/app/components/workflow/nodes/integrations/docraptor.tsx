import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const DocraptorIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg light="/icons/docraptor.svg" dark="/icons/docraptor-dark.svg" className={className} style={style} {...props} ref={ref} />
    ),
);
DocraptorIcon.displayName = 'DocraptorIcon';

export const DocraptorNode: NodeDefinition = {
    type: 'automation-docraptor',
    label: 'DocRaptor',
    description: 'Generate PDF and Excel files, host documents, and manage asynchronous jobs',
    category: 'documents',
    keywords: ['docraptor', 'html', 'pdf', 'excel', 'xls', 'xlsx'],
    Icon: DocraptorIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={DocraptorIcon} iconColor="" />),
};
