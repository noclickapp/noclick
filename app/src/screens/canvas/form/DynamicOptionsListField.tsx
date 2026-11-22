// DynamicOptionsListField - a list-valued config field whose items come from
// x-dynamic-options (e.g. the chats a WhatsApp trigger listens to). Each item is
// one DynamicOptionsField, plus a trailing empty one for the next pick, so loading,
// search, custom entry and {{references}} work exactly as in a single picker.
import { X } from 'lucide-react';
import { listLabels } from '@/screens/canvas/stepSchema';
import {
    DynamicOptionsField,
    type DynamicOptionsFieldProps,
} from './DynamicOptionsField';
import { valueToText } from './valueText';

type DynamicOptionsListFieldProps = Omit<
    DynamicOptionsFieldProps,
    'onChange'
> & {
    onChange: (key: string, value: unknown) => void;
};

export function DynamicOptionsListField({
    fieldKey,
    value,
    onChange,
    config,
    ...picker
}: DynamicOptionsListFieldProps) {
    const items = Array.isArray(value)
        ? value.map(valueToText).filter((v) => v.trim() !== '')
        : [];
    const labels = listLabels(config, fieldKey);
    const labelKey = `${fieldKey}__label`;

    const setItems = (next: string[]) =>
        onChange(fieldKey, [
            ...new Set(next.map((v) => v.trim()).filter(Boolean)),
        ]);
    const setLabel = (item: string, label: string) => {
        const next = { ...labels };
        if (label && label !== item) next[item] = label;
        else delete next[item];
        onChange(labelKey, next);
    };

    return (
        <div className="space-y-1.5">
            {[...items, ''].map((item, i) => {
                const rowKey = `${fieldKey}.${i}`;
                // The picker writes a value, then its label: the label belongs to that new value.
                let picked = item;
                const onRowChange = (key: string, next: string) => {
                    if (key === rowKey) {
                        picked = next;
                        setItems(
                            i < items.length
                                ? items.map((v, j) => (j === i ? next : v))
                                : [...items, next]
                        );
                    } else if (key === `${rowKey}__label` && picked) {
                        setLabel(picked, next);
                    }
                };
                return (
                    <div key={i} className="flex items-center gap-1.5">
                        <div className="min-w-0 flex-1">
                            <DynamicOptionsField
                                {...picker}
                                fieldKey={rowKey}
                                value={item}
                                onChange={onRowChange}
                                config={{
                                    ...config,
                                    [`${rowKey}__label`]: labels[item] ?? '',
                                }}
                            />
                        </div>
                        {i < items.length && (
                            <button
                                type="button"
                                aria-label="Remove item"
                                onClick={() => {
                                    setItems(items.filter((_, j) => j !== i));
                                    setLabel(item, '');
                                }}
                                className="p-1 text-muted-foreground dark:text-zinc-500 hover:text-red-400 transition-colors"
                            >
                                <X className="w-3.5 h-3.5" />
                            </button>
                        )}
                    </div>
                );
            })}
        </div>
    );
}
