// Native Landbot Platform node for channels, customers and custom fields.
// Uses the official vendor asset and keeps conversation delivery out of this node.
import { forwardRef, memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
// Vector brand artwork from https://landbot.io
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <ThemedBrandImg light="/icons/landbot-brand-vector.svg" dark="/icons/landbot-brand-vector-dark.svg" className={className} style={style} />
);

const LandbotIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
  ({ className, style, ...props }, ref) => <img ref={ref} src="/icons/landbot.svg" alt="" className={className} style={style} {...props} />,
);
LandbotIcon.displayName = 'LandbotIcon';
const LandbotNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />;

export const LandbotNode: NodeDefinition = {
  type: 'automation-landbot',
  label: 'Landbot',
  description: 'Platform channel/customer metadata and customer-field management',
  category: 'support',
  Icon: OfficialBrandIcon,
  iconColor: '',
  dimensions: { width: 90, height: 90, iconSize: 48 },
  component: memo(LandbotNodeComponent),
};
