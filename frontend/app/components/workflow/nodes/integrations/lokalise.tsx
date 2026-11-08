// Lokalise's native node exposes translation project reads and writes.
// This definition makes its generated operations available in both workflow catalogs.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const LokaliseIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/lokalise.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const LokaliseNode: NodeDefinition = {
    type: 'automation-lokalise', label: 'Lokalise',
    description: 'Manage localization projects, keys, translations, languages, tasks and comments',
    keywords: ['translation', 'localization', 'localisation', 'i18n'],
    Icon: LokaliseIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={LokaliseIcon} iconColor="" />),
};
