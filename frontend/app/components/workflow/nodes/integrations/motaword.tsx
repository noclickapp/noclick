import { forwardRef, memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import {
    NodeDefinition,
    SvgIconComponent,
} from '~/components/workflow/nodes/types';

const MotaWordIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <>
        <img
            {...props}
            ref={ref}
            src="/icons/motaword.svg"
            alt=""
            className={`dark:hidden ${className || ''}`}
            style={style}
        />
        <img
            {...props}
            src="/icons/motaword-dark.svg"
            alt=""
            className={` hidden dark:block ${className || ''}`}
            style={style}
        />
    </>
));
MotaWordIcon.displayName = 'MotaWordIcon';

export const MotaWordNode: NodeDefinition = {
    type: 'automation-motaword',
    label: 'MotaWord',
    description:
        'Automate translation projects, source documents, progress and project milestone callbacks.',
    category: 'documents',
    keywords: ['translation', 'localization', 'MotaWord API', 'glossary'],
    Icon: MotaWordIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={MotaWordIcon} iconColor="" />
    )),
};
