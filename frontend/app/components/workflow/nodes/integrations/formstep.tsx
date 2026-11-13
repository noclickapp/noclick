import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import {
    NodeDefinition,
    SvgIconComponent,
} from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const FormstepIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <ThemedBrandImg light="/icons/formstep.svg" dark="/icons/formstep-dark.svg" className={className} style={style} {...props} ref={ref} />
));
FormstepIcon.displayName = 'FormstepIcon';

export const FormstepNode: NodeDefinition = {
    type: 'automation-formstep',
    label: 'Formstep',
    description: 'Automate forms, requests, submissions and signed form events',
    category: 'forms',
    Icon: FormstepIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo(function FormstepComponent(props: NodeProps) {
        return <AutomationNode {...props} Icon={FormstepIcon} iconColor="" />;
    }),
};
