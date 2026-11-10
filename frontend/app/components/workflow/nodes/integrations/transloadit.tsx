import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const TransloaditIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <>
            <img ref={ref} src="/icons/transloadit.svg" alt="" className={`${className ?? ''} dark:hidden`} style={{ ...style, objectFit: 'contain' }} {...props} />
            <img src="/icons/transloadit-dark.svg" alt="" className={`${className ?? ''} hidden dark:block`} style={{ ...style, objectFit: 'contain' }} {...props} />
        </>
    ),
);
TransloaditIcon.displayName = 'TransloaditIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const TransloaditNode: NodeDefinition = {
    type: 'automation-transloadit',
    label: 'Transloadit',
    category: 'media',
    description: 'Automate media processing, Assemblies, Templates and credential metadata',
    Icon: TransloaditIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TransloaditIcon} iconColor="" />),
};
