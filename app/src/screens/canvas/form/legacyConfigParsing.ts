// Some older workflow configs passed through an HTML/XML transport before being
// stored. Decode one layer of the four entities that can occur in their JSON.
// A single replacement pass is intentional: chained replacements can decode a
// double-encoded value (for example, `&amp;quot;`) twice and corrupt user data.
const LEGACY_HTML_ENTITIES: Record<string, string> = {
    '&quot;': '"',
    '&amp;': '&',
    '&lt;': '<',
    '&gt;': '>',
};

export function decodeLegacyHtmlEntities(value: string): string {
    return value.replace(
        /&(quot|amp|lt|gt);/g,
        (entity) => LEGACY_HTML_ENTITIES[entity]
    );
}
