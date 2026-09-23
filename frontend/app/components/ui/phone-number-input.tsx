// Phone number entry with a country picker (flag + calling code), preselected
// to the visitor's country and formatted as they type (react-phone-number-input).
// The value is E.164, what every backend phone seam takes; it rides a hidden
// input named `name` so plain forms submit it.
import { useState } from 'react';
import PhoneInput, { type Value } from 'react-phone-number-input';
import 'react-phone-number-input/style.css';
import { useDetectedCountry } from '~/hooks/useDetectedCountry';
import { cn } from '~/lib/utils';

interface PhoneNumberInputProps {
    name: string;
    id?: string;
    disabled?: boolean;
    className?: string;
    /** Controlled use: the E.164 value and its setter. */
    value?: string;
    onChange?: (e164: string) => void;
}

export function PhoneNumberInput({
    name,
    id,
    disabled,
    className,
    value,
    onChange,
}: PhoneNumberInputProps) {
    const detected = useDetectedCountry();
    const [own, setOwn] = useState<string>('');
    const current = value ?? own;
    return (
        <div
            className={cn(
                'nc-phone-input flex h-11 w-full items-center rounded-xl border border-input bg-background pl-4 text-sm text-foreground transition-colors focus-within:border-foreground',
                disabled && 'opacity-60',
                className
            )}
        >
            <PhoneInput
                id={id}
                international
                withCountryCallingCode
                countryCallingCodeEditable={false}
                defaultCountry={detected}
                value={(current || undefined) as Value | undefined}
                onChange={(next) => (onChange ?? setOwn)(next ?? '')}
                disabled={disabled}
                autoComplete="tel"
                className="flex h-full w-full items-center gap-3"
                numberInputProps={{
                    className:
                        'h-full w-full min-w-0 border-l border-input bg-transparent pl-3 pr-4 outline-none placeholder:text-muted-foreground',
                }}
            />
            <input type="hidden" name={name} value={current} />
        </div>
    );
}
