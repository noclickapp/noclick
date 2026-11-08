import { forwardRef } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const CrowdinIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/crowdin.svg"
        alt=""
        className={className}
        style={style}
        {...props}
    />
));
CrowdinIcon.displayName = 'CrowdinIcon';

const CrowdinNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={CrowdinIcon} iconColor="" />
);

export const CrowdinNode: NodeDefinition = {
    type: 'automation-crowdin',
    label: 'Crowdin',
    description:
        'Localization projects, files, strings, translations, and glossaries',
    Icon: CrowdinIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: CrowdinNodeComponent,
};
