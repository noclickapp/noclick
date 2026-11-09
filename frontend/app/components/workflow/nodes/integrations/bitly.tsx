import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const BitlyIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/bitly.svg" alt="" className={className} style={style} {...props} />
    )
);
BitlyIcon.displayName = 'BitlyIcon';

const BitlyNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={BitlyIcon} iconColor="" />;
};

export const BitlyNode: NodeDefinition = {
    type: 'automation-bitly',
    label: 'Bitly',
    category: 'marketing',
    description: 'Short links, QR codes, and engagement analytics',
    Icon: BitlyIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(BitlyNodeComponent),
};
