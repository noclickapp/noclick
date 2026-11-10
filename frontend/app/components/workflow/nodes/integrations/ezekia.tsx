import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const EzekiaIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <>
            <img ref={ref} src="/icons/ezekia.svg" alt="" className={`${className ?? ''} dark:hidden`} style={{ ...style, objectFit: 'contain' }} {...props} />
            <img src="/icons/ezekia-dark.svg" alt="" className={`${className ?? ''} hidden dark:block`} style={{ ...style, objectFit: 'contain' }} {...props} />
        </>
    ),
);
EzekiaIcon.displayName = 'EzekiaIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const EzekiaNode: NodeDefinition = {
    type: 'automation-ezekia',
    label: 'Ezekia',
    description: 'Manage recruiting people, companies, search projects and tasks',
    category: 'hr-recruiting',
    Icon: EzekiaIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={EzekiaIcon} iconColor="" />),
};
