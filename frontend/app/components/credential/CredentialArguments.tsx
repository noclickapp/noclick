// Immutable tool arguments shared by individual and grouped approval reviews.
// Values render as text, so reviewing a message can never execute its HTML or scripts.
export function CredentialArguments({
    arguments: args,
}: {
    arguments: Record<string, unknown>;
}) {
    return (
        <dl className="mt-6 space-y-5">
            {Object.entries(args || {})
                .filter(
                    ([, value]) =>
                        value != null &&
                        value !== '' &&
                        (!Array.isArray(value) || value.length > 0)
                )
                .map(([key, value]) => (
                    <div key={key}>
                        <dt className="mb-1.5 text-xs capitalize text-muted-foreground">
                            {key.replaceAll('_', ' ')}
                        </dt>
                        <dd className="max-h-72 overflow-auto whitespace-pre-wrap break-words text-sm leading-6">
                            {typeof value === 'string'
                                ? value
                                : Array.isArray(value) &&
                                    value.every(
                                        (item) => typeof item === 'string'
                                    )
                                  ? value.join('\n')
                                  : JSON.stringify(value, null, 2)}
                        </dd>
                    </div>
                ))}
        </dl>
    );
}
