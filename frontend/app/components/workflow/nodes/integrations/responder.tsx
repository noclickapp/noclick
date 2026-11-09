// Responder exposes list, subscriber and consent actions from its published V2 API.
// This definition lets the canvas and integration catalog discover the node.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const ResponderIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/responder.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
ResponderIcon.displayName = 'ResponderIcon';

export const ResponderNode: NodeDefinition = {
    type: 'automation-responder',
    label: 'Responder (רב מסר)',
    description: 'Manage mailing lists, subscribers, consent, tags and personal fields',
    category: 'marketing',
    keywords: ['responder', 'רב מסר', 'rav meser', 'rav messer', 'email marketing'],
    Icon: ResponderIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ResponderIcon} iconColor="" />),
};
