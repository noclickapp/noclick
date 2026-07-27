// The action picker for a node, wired straight from its schema — options,
// labels, categories, trigger flags, tier badges and search keywords all come
// from utils/operationHelpers.
//
// Added so the Run popup can let someone choose an action without leaving it.
// The config panel renders OperationPicker too, but with extra concerns the
// popup has no use for (hiding operations that clash with the selected
// credential, an AI-autofill header action, and picker-open state shared with
// the rest of the panel), so it keeps its own wiring; the per-option accessors
// underneath are what the two share.
import { useState } from 'react';
import { getNodeMetadata } from './nodes/nodeRegistry';
import { OperationPicker } from './OperationPicker';
import { getSchemaInfo } from '~/utils/schemaFieldExtractor';
import {
    getOptionDisplayName,
    getOperationCategory,
    getOperationDescription,
    getOperationIsTrigger,
    getOperationKeywords,
    getOperationTierLabel,
} from '~/utils/operationHelpers';

interface NodeOperationPickerProps {
    nodeType: string;
    /** Currently selected operation, if any. */
    operation?: string;
    onOperationChange: (operation: string) => void;
}

export function NodeOperationPicker({
    nodeType,
    operation,
    onOperationChange,
}: NodeOperationPickerProps) {
    const schemaInfo = getSchemaInfo(nodeType);
    // Open by default when nothing is chosen — the same rule NodeConfig uses,
    // and the reason this is on screen at all.
    const [isOpen, setIsOpen] = useState(!operation);

    if (!schemaInfo?.hasDiscriminator) return null;
    const { options, discriminator } = schemaInfo;
    const selectedIndex = operation
        ? (discriminator.valueToOptionIndex.get(operation) ?? 0)
        : 0;
    const meta = getNodeMetadata(nodeType);

    return (
        <OperationPicker
            options={options}
            selectedIndex={selectedIndex}
            onSelect={(idx) => {
                const value = discriminator.optionToValue.get(idx);
                if (value) onOperationChange(value);
                setIsOpen(false);
            }}
            getOptionLabel={(idx) => getOptionDisplayName(schemaInfo, idx)}
            getOptionCategory={(idx) => getOperationCategory(nodeType, idx)}
            getOptionIsTrigger={(idx) => getOperationIsTrigger(nodeType, idx)}
            getOptionTierLabel={(idx) => getOperationTierLabel(nodeType, idx)}
            getOptionKeywords={(idx) => getOperationKeywords(nodeType, idx)}
            getOptionDescription={(idx) =>
                getOperationDescription(nodeType, idx) ?? ''
            }
            hiddenIndices={undefined}
            isOpen={isOpen}
            autoFocusOnOpen={false}
            onOpen={() => setIsOpen(true)}
            onClose={() => setIsOpen(false)}
            hasExplicitSelection={Boolean(operation)}
            NodeIcon={meta?.Icon}
            nodeIconColor={meta?.iconColor}
        />
    );
}
