import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import {
    NodeDefinition,
    SvgIconComponent,
} from '~/components/workflow/nodes/types';

const VTEXIcon: SvgIconComponent = ({
    className,
    style,
}: React.ImgHTMLAttributes<HTMLImageElement>) => (
    <>
        <img
            src="/icons/vtex.svg"
            alt=""
            className={`dark:hidden ${className}`}
            style={style}
        />
        <img
            src="/icons/vtex-dark.svg"
            alt=""
            className={`${className} hidden dark:block`}
            style={style}
        />
    </>
);
VTEXIcon.displayName = 'VTEXIcon';

export const VTEXNode: NodeDefinition = {
    type: 'automation-vtex',
    label: 'VTEX Orders',
    description:
        'Automate orders, fulfillment, invoices, tracking, payments, and order change notifications.',
    category: 'ecommerce',
    keywords: ['VTEX', 'Orders API', 'ecommerce', 'fulfillment', 'OMS'],
    Icon: VTEXIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={VTEXIcon} iconColor="" />
    )),
};
