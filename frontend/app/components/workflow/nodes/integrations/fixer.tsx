import { memo, forwardRef } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const FixerIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <>
            <img ref={ref} src="/icons/fixer.svg" alt="" className={`${className ?? ''} dark:hidden`}
                style={{ ...style, objectFit: 'contain' }} {...props} />
            <img src="/icons/fixer-dark.svg" alt="" className={`${className ?? ''} hidden dark:block`}
                style={{ ...style, objectFit: 'contain' }} {...props} />
        </>
    ),
);
FixerIcon.displayName = 'FixerIcon';

export const FixerNode: NodeDefinition = {
    type: 'automation-fixer',
    label: 'Fixer',
    description: 'Currency exchange rates, conversions, time series and fluctuations',
    category: 'finance-accounting',
    keywords: ['forex', 'exchange rates', 'currency conversion', 'fixer.io'],
    Icon: FixerIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={FixerIcon} iconColor="" />),
};
