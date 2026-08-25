// Node ID generator utility for creating short, human-readable workflow node IDs.
// Replaces long timestamp-based IDs (e.g., "automation-telegram-1732185234567-846")
// with shorter, readable ones (e.g., "telegram_a7bx").
// Also supports label-based IDs (e.g., "send_welcome_email_x7k2").

/**
 * Maps full node type names to shorter, human-readable prefixes.
 * These prefixes are used as the first part of generated node IDs.
 */
const NODE_TYPE_PREFIXES: Record<string, string> = {
    'automation-telegram': 'telegram',
    'automation-whatsapp': 'whatsapp',
    'automation-google-sheets': 'sheets',
    'automation-gmail': 'gmail',
    'automation-google': 'google',
    'agent': 'agent',
    'stickyNote': 'note',
    // Add new node types here as they're created
};

/**
 * Converts a label string to a URL-friendly slug.
 * Used to generate readable node IDs from user-provided labels.
 *
 * @param label - The label string to convert (e.g., "Send welcome email")
 * @returns A slug version (e.g., "send_welcome_email")
 */
export function labelToSlug(label: string): string {
    return label
        .toLowerCase()
        .trim()
        .replace(/[^a-z0-9\s-]/g, '') // Remove special characters except spaces and hyphens
        .replace(/[\s-]+/g, '_')       // Replace spaces and hyphens with underscores
        .replace(/^_+|_+$/g, '')       // Remove leading/trailing underscores
        .slice(0, 30);                  // Limit length to keep IDs manageable
}

/**
 * Generates a short alphanumeric suffix for uniqueness.
 * Uses base36 encoding (0-9, a-z) for compact representation.
 *
 * @param length - Number of characters to generate (default: 4)
 * @returns A random alphanumeric string
 */
export function generateShortSuffix(length: number = 4): string {
    const chars = '0123456789abcdefghijklmnopqrstuvwxyz';
    let result = '';
    for (let i = 0; i < length; i++) {
        result += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    return result;
}

/**
 * Generates a short, human-readable node ID.
 *
 * If a label is provided, the ID will be based on the slugified label:
 *   Format: {slug}_{suffix}
 *   Example: "send_welcome_email_x7k2", "fetch_user_data_a3bx"
 *
 * Otherwise, uses the node type prefix:
 *   Format: {prefix}_{suffix}
 *   Example: "telegram_a7bx", "sheets_k9mz", "agent_p5q2"
 *
 * @param nodeType - The full node type (e.g., "automation-telegram")
 * @param label - Optional user-provided label for more meaningful IDs
 * @returns A short, unique node ID
 */
export function generateNodeId(nodeType: string, label?: string): string {
    let prefix: string;

    if (label && label.trim()) {
        // Use slugified label for more meaningful IDs
        prefix = labelToSlug(label);
        // Fall back to type prefix if slug is empty (e.g., label was all special characters)
        if (!prefix) {
            prefix = NODE_TYPE_PREFIXES[nodeType] || nodeType.replace(/^automation-/, '');
        }
    } else {
        prefix = NODE_TYPE_PREFIXES[nodeType] || nodeType.replace(/^automation-/, '');
    }

    const suffix = generateShortSuffix();
    return `${prefix}_${suffix}`;
}

/**
 * Generates a short edge ID from source and target node IDs.
 *
 * Format: e_{shortSuffix}
 * Example: "e_x7k2"
 *
 * @returns A short, unique edge ID
 */
export function generateEdgeId(): string {
    return `e_${generateShortSuffix()}`;
}

/**
 * Gets the readable prefix for a node type.
 * Useful for display purposes.
 *
 * @param nodeType - The full node type
 * @returns The human-readable prefix
 */
export function getNodeTypePrefix(nodeType: string): string {
    return NODE_TYPE_PREFIXES[nodeType] || nodeType.replace(/^automation-/, '');
}
