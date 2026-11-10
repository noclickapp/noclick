import { forwardRef, memo } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const DocumensoIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <>
        <img
            ref={ref}
            src="/icons/documenso.svg"
            alt=""
            className={`${className ?? ''} dark:hidden`}
            style={style}
            {...props}
        />
        <img
            src="/icons/documenso-dark.svg"
            alt=""
            className={`${className ?? ''} hidden dark:block`}
            style={style}
            {...props}
        />
    </>
));
DocumensoIcon.displayName = 'DocumensoIcon';

export const DocumensoNode: NodeDefinition = {
    type: 'automation-documenso',
    label: 'Documenso',
    description: 'Prepare, send, and track signature envelopes',
    category: 'documents',
    Icon: DocumensoIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={DocumensoIcon} iconColor="" />
    )),
};
