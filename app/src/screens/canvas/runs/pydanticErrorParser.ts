// Utility to parse Pydantic validation errors into human-readable, field-specific errors.
// Used to display execution errors on workflow nodes with field highlighting.

export interface ParsedFieldError {
    fieldPath: string;       // The field path in the config (e.g., "website_url" or "hardware.gpu_type")
    fieldName: string;       // Human-readable field name (e.g., "Website URL")
    errorType: string;       // Error type (e.g., "missing", "string_type", "url_parsing")
    message: string;         // Human-readable error message
    rawMessage: string;      // Original error message from Pydantic
}

export interface ParsedExecutionError {
    summary: string;         // Overall error summary
    fieldErrors: ParsedFieldError[];
    isValidationError: boolean;  // True if this is a Pydantic validation error
    rawError: string;        // Original error string
}

// Convert snake_case or camelCase to human-readable title case
function toTitleCase(str: string): string {
    return str
        .replace(/_/g, ' ')
        .replace(/([a-z])([A-Z])/g, '$1 $2')
        .replace(/\b\w/g, c => c.toUpperCase());
}

// Generate human-readable error message based on error type
function getHumanReadableMessage(errorType: string, fieldName: string): string {
    switch (errorType) {
        case 'missing':
            return `${fieldName} is required`;
        case 'string_type':
            return `${fieldName} must be a text value`;
        case 'int_type':
        case 'integer_type':
            return `${fieldName} must be a number`;
        case 'bool_type':
        case 'boolean_type':
            return `${fieldName} must be true or false`;
        case 'url_parsing':
        case 'url_type':
            return `${fieldName} must be a valid URL`;
        case 'email_type':
            return `${fieldName} must be a valid email address`;
        case 'json_invalid':
            return `${fieldName} contains invalid JSON`;
        case 'value_error':
            return `${fieldName} has an invalid value`;
        case 'enum':
            return `${fieldName} must be one of the allowed options`;
        case 'string_too_short':
            return `${fieldName} is too short`;
        case 'string_too_long':
            return `${fieldName} is too long`;
        default:
            return `${fieldName} is invalid`;
    }
}

// Parse a single Pydantic error line to extract field path and error type
// Format: "  Field required [type=missing, input_value=..., input_type=dict]"
function parseErrorDetails(line: string): { errorType: string; rawMessage: string } | null {
    // Match the error type from [type=xxx, ...]
    const typeMatch = line.match(/\[type=([^,\]]+)/);
    if (typeMatch) {
        return {
            errorType: typeMatch[1],
            rawMessage: line.trim()
        };
    }

    // Fallback: just use the line as raw message
    const trimmed = line.trim();
    if (trimmed && !trimmed.startsWith('For further information')) {
        return {
            errorType: 'unknown',
            rawMessage: trimmed
        };
    }

    return null;
}

// Extract the UI field key from a Pydantic field path
// Pydantic paths look like: "config.operation_value.field_name" or "config.field_name"
// We need to map to UI keys like: "field_name" or "nested.field_name"
function extractUIFieldKey(fieldPath: string): string {
    // Remove "config." prefix if present
    let path = fieldPath.startsWith('config.') ? fieldPath.slice(7) : fieldPath;

    // The path might have the discriminator value as the first segment
    // e.g., "miniflux_discover.website_url" where "miniflux_discover" is the operation value
    // We want to return just "website_url" for top-level fields
    // But for nested objects, we want "hardware.gpu_type"

    const parts = path.split('.');

    // If there are 2+ parts and this looks like a discriminator pattern (operation_value.field)
    // return just the field part. Otherwise return the full path.
    if (parts.length >= 2) {
        // Check if first part looks like a discriminator value (contains underscore operation pattern)
        // Common patterns: miniflux_discover, read_channel, send_message
        const firstPart = parts[0];
        const isLikelyDiscriminator = /^[a-z]+_[a-z]+$/.test(firstPart) ||
                                       firstPart.includes('_') && parts.length === 2;

        if (isLikelyDiscriminator && parts.length === 2) {
            return parts[1]; // Return just the field name
        }

        // For deeper nesting or non-discriminator patterns, return from second part onwards
        // This handles cases like "config.operation.nested.field" -> "nested.field"
        if (parts.length > 2) {
            return parts.slice(1).join('.');
        }
    }

    return path;
}

/**
 * Parse a Pydantic validation error string into structured field errors.
 *
 * Example input:
 * ```
 * Invalid configuration: 1 validation error for RSSNodeConfig
 * config.miniflux_discover.website_url
 *   Field required [type=missing, input_value={'operation': 'miniflux_discover'}, input_type=dict]
 *     For further information visit https://errors.pydantic.dev/2.11/v/missing
 * ```
 *
 * @param errorString The raw error string from workflow execution
 * @returns Parsed error with field-specific information
 */
export function parseExecutionError(errorString: string): ParsedExecutionError {
    const result: ParsedExecutionError = {
        summary: '',
        fieldErrors: [],
        isValidationError: false,
        rawError: errorString
    };

    // Check if this is a Pydantic validation error
    const isValidationError = errorString.includes('validation error') ||
                               errorString.includes('[type=') ||
                               errorString.includes('Field required');

    if (!isValidationError) {
        // Not a validation error - return as-is
        result.summary = errorString;
        return result;
    }

    result.isValidationError = true;

    // Split into lines and parse
    const lines = errorString.split('\n');

    // First line is usually the summary
    if (lines.length > 0) {
        result.summary = lines[0].trim();
    }

    // Parse field errors - they come in pairs:
    // Line 1: field path (e.g., "config.miniflux_discover.website_url")
    // Line 2: error details (e.g., "  Field required [type=missing, ...]")
    let currentFieldPath: string | null = null;

    for (let i = 1; i < lines.length; i++) {
        const line = lines[i];
        const trimmedLine = line.trim();

        // Skip empty lines and "For further information" links
        if (!trimmedLine || trimmedLine.startsWith('For further information')) {
            continue;
        }

        // Check if this is a field path (no leading whitespace or minimal whitespace)
        // Field paths don't start with common error keywords
        const isFieldPath = !line.startsWith('  ') ||
                           (line.startsWith(' ') && !line.startsWith('    ') &&
                            !trimmedLine.startsWith('Field') &&
                            !trimmedLine.startsWith('[type='));

        // Actually, let's detect by content: field paths are like "config.xxx" or "xxx.yyy"
        const looksLikeFieldPath = /^[a-z_][a-z0-9_.]*$/i.test(trimmedLine) &&
                                   !trimmedLine.includes(' ');

        if (looksLikeFieldPath && !currentFieldPath) {
            currentFieldPath = trimmedLine;
        } else if (currentFieldPath) {
            // This should be the error details line
            const details = parseErrorDetails(line);

            if (details) {
                const uiFieldKey = extractUIFieldKey(currentFieldPath);
                const fieldName = toTitleCase(uiFieldKey.split('.').pop() || uiFieldKey);

                result.fieldErrors.push({
                    fieldPath: uiFieldKey,
                    fieldName: fieldName,
                    errorType: details.errorType,
                    message: getHumanReadableMessage(details.errorType, fieldName),
                    rawMessage: details.rawMessage
                });
            }

            currentFieldPath = null;
        }
    }

    // Generate summary if we have field errors
    if (result.fieldErrors.length > 0 && result.summary.includes('validation error')) {
        const count = result.fieldErrors.length;
        result.summary = `${count} field${count > 1 ? 's' : ''} ${count > 1 ? 'need' : 'needs'} attention`;
    }

    return result;
}

/**
 * Create a map of field keys to their error messages for easy lookup.
 *
 * @param parsedError The parsed execution error
 * @returns Map from field key to array of error messages
 */
export function getFieldErrorMap(parsedError: ParsedExecutionError): Record<string, string[]> {
    const errorMap: Record<string, string[]> = {};

    for (const fieldError of parsedError.fieldErrors) {
        if (!errorMap[fieldError.fieldPath]) {
            errorMap[fieldError.fieldPath] = [];
        }
        errorMap[fieldError.fieldPath].push(fieldError.message);
    }

    return errorMap;
}
