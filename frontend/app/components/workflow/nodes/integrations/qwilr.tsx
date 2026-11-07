import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const QwilrIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/qwilr.svg" alt="" className={className} style={style} {...props} />
    )
);
QwilrIcon.displayName = 'QwilrIcon';

export const QwilrNode: NodeDefinition = {
    type: 'automation-qwilr',
    label: 'Qwilr',
    description: 'Proposal page metadata and unpublished draft workflows',
    keywords: ['proposal', 'quote', 'sales document', 'saved block', 'template', 'draft'],
    Icon: QwilrIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={QwilrIcon} iconColor="" />),
};
