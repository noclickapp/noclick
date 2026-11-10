import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import {
    NodeDefinition,
    SvgIconComponent,
} from '~/components/workflow/nodes/types';

const FireberryIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <>
        <img
            ref={ref}
            src="/icons/fireberry.svg"
            alt=""
            className={`${className ?? ''} dark:hidden`}
            style={{ ...style, objectFit: 'contain' }}
            {...props}
        />
        <img
            src="/icons/fireberry-dark.svg"
            alt=""
            className={`${className ?? ''} hidden dark:block`}
            style={{ ...style, objectFit: 'contain' }}
            {...props}
        />
    </>
));
FireberryIcon.displayName = 'FireberryIcon';

// Exact publisher asset; provenance is recorded beside it.
export const FireberryNode: NodeDefinition = {
    type: 'automation-fireberry',
    label: 'Fireberry',
    category: 'crm-sales',
    description:
        'Create, read, update and delete CRM accounts, contacts, opportunities and tasks',
    Icon: FireberryIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo(function FireberryCanvasNode(props: NodeProps) {
        return <AutomationNode {...props} Icon={FireberryIcon} iconColor="" />;
    }),
};
