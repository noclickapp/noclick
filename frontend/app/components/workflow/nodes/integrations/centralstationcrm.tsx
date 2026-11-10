import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';


// Unmodified compact brand asset from https://centralstationcrm.com
import type { CSSProperties as BrandCSSProperties } from 'react';
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <>
        <img src="/icons/centralstationcrm-brand.svg" alt="" aria-hidden="true" className={`${className ?? ''} dark:hidden`}
            style={{ ...style, objectFit: 'contain' } as BrandCSSProperties} />
        <img src="/icons/centralstationcrm-brand-dark.svg" alt="" aria-hidden="true" className={`${className ?? ''} hidden dark:block`}
            style={{ ...style, objectFit: 'contain' } as BrandCSSProperties} />
    </>
);

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const CentralStationCRMNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />
);

export const CentralStationCRMNode: NodeDefinition = {
    type: 'automation-centralstationcrm',
    label: 'CentralStationCRM',
    description: 'Contacts, companies, deals, projects, and tasks',
    category: 'crm-sales',
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(CentralStationCRMNodeComponent),
};
