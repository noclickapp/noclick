// OpenStatus metadata node uses its exact official published vector asset.
// Native forms and selection come from the generated typed schema; no generic RPC editor.
import { forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
// Vector brand artwork from https://www.openstatus.dev
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <ThemedBrandImg light="/icons/openstatus.svg" dark="/icons/openstatus-dark.svg" className={className} style={style} />
);

export const OpenStatusIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => <img ref={ref} src="/icons/openstatus.svg" alt="" className={className} style={style} {...props} />,
);
OpenStatusIcon.displayName = 'OpenStatusIcon';
export const OpenStatusNode: NodeDefinition = {
    type: 'automation-openstatus', category: 'monitoring', label: 'OpenStatus', description: 'Protected monitoring and status-page metadata reads',
    Icon: OfficialBrandIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 },
    component: (props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />,
};
