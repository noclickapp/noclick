// Choosing in the app's own dropdown (`@/ui/FieldSelect`, Radix's select) as a person does: open it, click the option.
// Radix opens and picks on a click that isn't a mouse's pointer, which is what fireEvent's is; happy-dom has no
// ResizeObserver, which its list measures itself with.
import { fireEvent, screen } from '@testing-library/react';

export function pick(trigger: HTMLElement, text: string): void {
    if (!('ResizeObserver' in globalThis)) {
        (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
            observe() {}
            unobserve() {}
            disconnect() {}
        };
    }
    fireEvent.click(trigger);
    const options = screen.getAllByRole('option');
    const option = options.find((o) => (o.textContent ?? '').trim().startsWith(text));
    if (!option) throw new Error(`No option "${text}" in ${options.map((o) => o.textContent).join(', ')}`);
    fireEvent.click(option);
}
