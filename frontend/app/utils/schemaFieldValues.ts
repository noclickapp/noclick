/** Unwrap only a single value type plus null, never a mixed-type union. */
export function fieldValueSchema(prop: any): any {
    if (!prop || typeof prop !== 'object') return prop;
    const alternatives = prop.anyOf || prop.oneOf;
    if (Array.isArray(alternatives)) {
        const values = alternatives.filter(option => option?.type !== 'null');
        if (values.length === 1 && values.length < alternatives.length) {
            const value = fieldValueSchema(values[0]);
            return { ...value, ...prop, type: value?.type, enum: prop.enum ?? value?.enum, items: prop.items ?? value?.items };
        }
    }
    if (Array.isArray(prop.type)) {
        const types = prop.type.filter((type: string) => type !== 'null');
        if (types.length === 1) return { ...prop, type: types[0] };
    }
    return prop;
}

export function fieldAllowsNull(prop: any): boolean {
    return prop?.type === 'null' || (Array.isArray(prop?.type) && prop.type.includes('null'))
        || (prop?.anyOf || prop?.oneOf || []).some((option: any) => option?.type === 'null');
}

export function enumLabel(value: unknown, index: number, labels?: any): string {
    const label = Array.isArray(labels) ? labels[index] : labels?.[String(value)];
    return String(label ?? (value === null ? 'None' : value));
}

/** Parse a complete numeric edit; partial text and unsafe integers stay text. */
export function numericFieldValue(text: string, type: 'integer' | 'number'): number | string {
    if (!/^[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(text)) return text;
    const value = Number(text);
    return Number.isFinite(value) && (type !== 'integer' || Number.isSafeInteger(value)) ? value : text;
}
