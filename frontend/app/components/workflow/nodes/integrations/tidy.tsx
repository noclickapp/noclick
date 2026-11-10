import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const TidyIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <>
            <img ref={ref} src="/icons/tidy.svg" alt="" className={`${className ?? ''} dark:hidden`} style={{ ...style, objectFit: 'contain' }} {...props} />
            <img src="/icons/tidy-dark.svg" alt="" className={`${className ?? ''} hidden dark:block`} style={{ ...style, objectFit: 'contain' }} {...props} />
        </>
    ),
);
TidyIcon.displayName = 'TidyIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const TidyNode: NodeDefinition = {
    type: 'automation-tidy',
    label: 'Tidy',
    category: 'nonprofit',
    keywords: ['TidyHQ'],
    description: 'TidyHQ contacts, memberships, events and invoices',
    Icon: TidyIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TidyIcon} iconColor="" />),
};
