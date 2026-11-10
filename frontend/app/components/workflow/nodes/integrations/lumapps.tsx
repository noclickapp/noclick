// LumApps native intranet node definition.
// Uses the current shared credential/config UI and the publisher's unmodified logo.
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';


// Unmodified publisher asset from https://developer.lumapps.com/assets/images/logo-H-color.svg
import type { CSSProperties as BrandCSSProperties } from 'react';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <ThemedBrandImg light="/icons/lumapps.svg" dark="/icons/lumapps-dark.svg" className={className} style={style} />
);

export const LumAppsNode: NodeDefinition = {
  type: 'automation-lumapps',
  label: 'LumApps',
  description: 'Employee intranet metadata and unpublished content drafts',
  category: 'communication',
  Icon: OfficialBrandIcon,
  iconColor: '',
  dimensions: { width: 90, height: 90, iconSize: 48 },
  component: (props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />,
};
