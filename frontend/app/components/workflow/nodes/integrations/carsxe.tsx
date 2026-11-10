// CarsXE vehicle data operations in the workflow canvas and integration catalogue.
// Uses the publisher's official icon; its source and hash are recorded beside it.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const CarsxeIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg light="/icons/carsxe.svg" dark="/icons/carsxe-dark.svg" className={className} style={style} {...props} ref={ref} />
    ),
);
CarsxeIcon.displayName = 'CarsxeIcon';

export const CarsxeNode: NodeDefinition = {
    type: 'automation-carsxe',
    label: 'CarsXE',
    description: 'Decode vehicles, check recalls and history, estimate values and submit batches',
    category: 'industry',
    Icon: CarsxeIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CarsxeIcon} iconColor="" />),
};
