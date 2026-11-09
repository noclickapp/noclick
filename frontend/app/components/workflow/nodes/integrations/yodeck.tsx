// Native Yodeck metadata node for supplied API tokens and a workspace witness.
// The original vendor SVG stays an external asset; no player or publishing controls are exposed.
import { memo, type SVGProps } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://www.yodeck.com/
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/yodeck.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
);

export const YodeckIcon = ({ className, style }: SVGProps<SVGSVGElement>) => (
  <img src="/icons/yodeck.svg" alt="Yodeck" className={className} style={style} />
);

export const YodeckNode: NodeDefinition = {
  type: 'automation-yodeck',
  label: 'Yodeck',
  category: 'media',
  description: 'Read workspace, folder, playlist and screen metadata',
  Icon: OfficialBrandIcon,
  iconColor: '',
  dimensions: { width: 90, height: 90, iconSize: 48 },
  component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />),
};
