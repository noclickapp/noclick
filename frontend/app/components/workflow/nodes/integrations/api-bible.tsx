import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const ApiBibleIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/api-bible.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
ApiBibleIcon.displayName = 'ApiBibleIcon';

export const ApiBibleNode: NodeDefinition = {
    type: 'automation-api-bible',
    label: 'API.Bible',
    category: 'content-research',
    description: 'Read and search licensed Bible translations, passages, verses and audio metadata',
    keywords: ['Api Bible', 'scripture', 'verses', 'translations'],
    Icon: ApiBibleIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ApiBibleIcon} iconColor="" />),
};
