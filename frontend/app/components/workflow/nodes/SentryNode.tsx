// Sentry error-tracking automation node definition.
// Provides workflow integration with the Sentry REST API (issues, projects,
// teams, releases + deploys, members, issue/metric alert rules, crons/monitors,
// dashboards, Discover queries, service hooks) plus service-hook triggers for
// new errors and alerts. Uses the react-icons Sentry mark (brand-purple on the
// canvas; the credentials view renders it neutral — see oauthProviders.ts).

import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import { SiSentry } from 'react-icons/si';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const SentryNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={SiSentry} iconColor="#6C5FC7" />;
};

export const SentryNode: NodeDefinition = {
    type: 'automation-sentry',
    label: 'Sentry',
    description: 'Sentry error-tracking automation',
    Icon: SiSentry,
    iconColor: '#6C5FC7',
    dimensions: DIMENSIONS,
    component: memo(SentryNodeComponent),
};
