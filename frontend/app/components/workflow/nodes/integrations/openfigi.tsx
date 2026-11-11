import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const OpenFIGIIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/openfigi.svg" alt="" aria-hidden="true" className={className} style={style} />
);

export const OpenFIGINode: NodeDefinition = {
    type: 'automation-openfigi', category: 'finance-accounting', label: 'OpenFIGI',
    description: 'Map financial identifiers to FIGIs, search instruments and read reference data',
    keywords: ['ISIN', 'CUSIP', 'SEDOL', 'FIGI', 'securities', 'ticker', 'financial instruments'],
    Icon: OpenFIGIIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OpenFIGIIcon} iconColor="" />),
};
