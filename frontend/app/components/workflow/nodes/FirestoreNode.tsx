// Google Cloud Firestore automation node definition.
// Provides workflow integration with the Firestore REST API v1 (documents,
// batch, queries, transactions, databases, indexes) via Google OAuth.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const FirestoreIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img ref={ref} src="/icons/firestore.svg" alt="" className={className} style={style} {...props} />
));
FirestoreIcon.displayName = 'FirestoreIcon';

const FirestoreNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={FirestoreIcon} iconColor="" />;
};

export const FirestoreNode: NodeDefinition = {
    type: 'automation-firestore',
    label: 'Firestore',
    description: 'Google Cloud Firestore automation',
    Icon: FirestoreIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(FirestoreNodeComponent),
};
