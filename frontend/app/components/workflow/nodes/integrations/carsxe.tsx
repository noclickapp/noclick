// CarsXE vehicle data operations in the workflow canvas and integration catalogue.
// Uses the publisher's official icon; its source and hash are recorded beside it.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const CarsxeIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <>
            <img ref={ref} src="/icons/carsxe.svg" alt="" className={`${className ?? ''} dark:hidden`} style={{ ...style, objectFit: 'contain' }} {...props} />
            <img src="/icons/carsxe-dark.svg" alt="" className={`${className ?? ''} hidden dark:block`} style={{ ...style, objectFit: 'contain' }} {...props} />
        </>
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
