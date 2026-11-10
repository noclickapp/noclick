// Registers Mezmo's Enterprise API operations in the canvas and integration catalog.
// The provider's official icon is retained with a provenance sidecar.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const MezmoIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <>
            <img ref={ref} src="/icons/mezmo.svg" alt="" className={`${className ?? ''} dark:hidden`} style={{ ...style, objectFit: 'contain' }} {...props} />
            <img src="/icons/mezmo-dark.svg" alt="" className={`${className ?? ''} hidden dark:block`} style={{ ...style, objectFit: 'contain' }} {...props} />
        </>
    ),
);
MezmoIcon.displayName = 'MezmoIcon';

export const MezmoNode: NodeDefinition = {
    type: 'automation-mezmo',
    label: 'Mezmo',
    description: 'Manage enterprise child accounts and monitor pipeline health and usage',
    category: 'monitoring',
    Icon: MezmoIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MezmoIcon} iconColor="" />),
};
