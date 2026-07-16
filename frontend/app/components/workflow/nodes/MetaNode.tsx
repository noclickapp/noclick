// Meta (Marketing / Ads / Business) automation node definition.
// Meta Marketing API: ad accounts, campaigns, ad sets, ads, creatives, audiences,
// insights, Conversions API, Lead Ads, catalogs, plus Business Management.

import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import { SiMeta } from 'react-icons/si';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };
const META_COLOR = 'text-[#0866FF]';

const MetaNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={SiMeta} iconColor={META_COLOR} />;
};

export const MetaNode: NodeDefinition = {
    type: 'automation-meta',
    label: 'Meta',
    description: 'Meta Marketing/Ads: campaigns, ads, audiences, insights & leads',
    Icon: SiMeta,
    iconColor: META_COLOR,
    dimensions: DIMENSIONS,
    component: memo(MetaNodeComponent),
};
