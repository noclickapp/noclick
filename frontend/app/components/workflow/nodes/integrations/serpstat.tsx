// Serpstat's fixed v4 JSON-RPC SEO reads and existing rank/audit results.
// Real data reads can consume API credits; this node never launches scans.
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://serpstat.com
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/serpstat.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
);

const SerpstatNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />;
export const SerpstatNode: NodeDefinition = {
  type: 'automation-serpstat', category: 'marketing', label: 'Serpstat', description: 'Domain and keyword analytics, backlink metrics and existing rank/audit results',
  Icon: OfficialBrandIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 }, component: SerpstatNodeComponent,
};
