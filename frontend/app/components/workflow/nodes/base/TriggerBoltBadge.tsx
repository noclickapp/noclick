// Bare amber bolt floating just left of a trigger node, where the input handle
// would be (triggers have no input handle; events enter here).

import { Zap } from 'lucide-react';

export const TriggerBoltBadge = () => (
    <div
        className="absolute pointer-events-none select-none"
        style={{ left: -22, top: '50%', transform: 'translateY(-50%)', zIndex: 10 }}
        title="Trigger — starts this workflow when its event fires"
    >
        <Zap
            className="w-4 h-4 text-amber-400"
            fill="currentColor"
            style={{ filter: 'drop-shadow(0 1px 3px rgba(0, 0, 0, 0.8))' }}
        />
    </div>
);
