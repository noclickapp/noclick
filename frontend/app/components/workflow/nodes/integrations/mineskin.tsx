import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const MineSkinIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <>
            <img ref={ref} {...props} src="/icons/mineskin.svg" alt="" className={`${className ?? ''} dark:hidden`} style={{ ...style, objectFit: 'contain' }} />
            <img {...props} src="/icons/mineskin-dark.svg" alt="" className={`${className ?? ''} hidden dark:block`} style={{ ...style, objectFit: 'contain' }} />
        </>
    ),
);
MineSkinIcon.displayName = 'MineSkinIcon';

export const MineSkinNode: NodeDefinition = {
    type: 'automation-mineskin',
    label: 'MineSkin API',
    description: 'Generate Minecraft skins, submit queue jobs, and read skins, capes and account details',
    category: 'developer-tools',
    keywords: ['Minecraft', 'skin', 'cape', 'texture', 'MineSkin'],
    Icon: MineSkinIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MineSkinIcon} iconColor="" />),
};
