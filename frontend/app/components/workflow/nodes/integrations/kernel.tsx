// Registers Kernel in the workflow catalog and canvas using its generated backend schema.
// The official provider mark helps people identify their browser automation connection.
import { memo, forwardRef } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const KernelIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/kernel.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
KernelIcon.displayName = 'KernelIcon';

export const KernelNode: NodeDefinition = {
    type: 'automation-kernel',
    label: 'Kernel',
    description: 'Automate cloud browsers, run Playwright, manage profiles and invoke app actions',
    category: 'developer-tools',
    keywords: ['browser automation', 'Playwright', 'cloud browser'],
    Icon: KernelIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={KernelIcon} iconColor="" />),
};
