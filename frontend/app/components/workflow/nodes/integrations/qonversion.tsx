// Native Qonversion v4 metadata node for products, definitions, configuration status and opted-in users.
// Uses the vector artwork from the provider SDK; credential and operation forms come from its generated native schema.
import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://raw.githubusercontent.com/qonversion/android-sdk/adeeeae489191328b1c75190d96c2930f5101737/sample/src/main/res/drawable/ic_qonversion.xml
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/qonversion-brand-vector.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };
const QonversionNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="#19191b" />;
export const QonversionNode: NodeDefinition = {
    type: 'automation-qonversion', category: 'finance-accounting', label: 'Qonversion',
    description: 'Read product, entitlement definition, configuration and safe user metadata',
    Icon: OfficialBrandIcon, iconColor: '#19191b', dimensions: DIMENSIONS, component: memo(QonversionNodeComponent),
};
