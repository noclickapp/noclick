import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const UrlscanioIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/urlscanio.svg"
        alt=""
        aria-hidden="true"
        className={className}
        style={{ ...style, objectFit: 'contain' }}
    />
);

export const UrlscanioNode: NodeDefinition = {
    type: 'automation-urlscanio',
    category: 'developer-tools',
    label: 'urlscan.io',
    keywords: ['Urlscanio', 'URL scanner', 'phishing', 'threat intelligence'],
    description:
        'Scan URLs, search results, investigate hosts and manage saved searches',
    Icon: UrlscanioIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(function UrlscanioComponent(props: NodeProps) {
        return <AutomationNode {...props} Icon={UrlscanioIcon} iconColor="" />;
    }),
};
