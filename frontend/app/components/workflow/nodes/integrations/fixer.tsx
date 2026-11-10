import { memo, forwardRef } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const FixerIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg light="/icons/fixer.svg" dark="/icons/fixer-dark.svg" className={className} style={style} {...props} ref={ref} />
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
