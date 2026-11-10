import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const FinancialDatasetsAIIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/financial-datasets-ai.svg" dark="/icons/financial-datasets-ai-dark.svg" className={className} style={style} />
);

export const FinancialDatasetsAINode: NodeDefinition = {
    type: 'automation-financial-datasets-ai', category: 'finance-accounting', label: 'Financial Datasets AI',
    keywords: ['financialdatasets', 'stock market', 'SEC', 'fundamentals', 'equities'],
    description: 'Query financial statements, prices, filings, ownership, news and macro data',
    Icon: FinancialDatasetsAIIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={FinancialDatasetsAIIcon} iconColor="" />),
};
