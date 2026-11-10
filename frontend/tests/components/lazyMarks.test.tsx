// @vitest-environment happy-dom
// Country flags and AI providers' brand marks load when first drawn, not with the page: each holds its place at its
// size until its module arrives, then draws, and the next one drawn is there at once.
import { cleanup, render, waitFor } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { CountryFlag } from '~/components/ui/country-picker';
import { getProviderMetadata, providerGlyph, ModelProvider } from '~/types/provider';

afterEach(cleanup);

it('draws a flag once the flags have loaded, and the next at once', async () => {
    const first = render(<CountryFlag country="FR" />);
    expect(first.container.querySelector('svg')).toBeNull();
    expect(first.container.querySelector('span[aria-hidden]')).not.toBeNull();
    await waitFor(() => expect(first.container.querySelector('svg')).not.toBeNull());
    const next = render(<CountryFlag country="DE" />);
    expect(next.container.querySelector('svg')).not.toBeNull();
});

it('draws no flag for a country it has none for', async () => {
    const { container } = render(<CountryFlag />);
    expect(container.querySelector('.lucide-globe')).not.toBeNull();
});

it("draws a provider's avatar and its glyph in their place once its mark has loaded", async () => {
    // Before its mark arrives each holds its place at its size; then the mark's own drawing takes it (@lobehub/icons
    // draws nothing under happy-dom, so the place giving way is what shows it arrived).
    const placeholder = (container: HTMLElement, size: number) => container.querySelector(`span[aria-hidden][style*="${size}px"]`);
    const avatar = render(<>{getProviderMetadata(ModelProvider.ANTHROPIC)!.icon}</>);
    const Glyph = providerGlyph(ModelProvider.ANTHROPIC)!;
    const glyph = render(<Glyph size={16} />);
    expect(placeholder(avatar.container, 32)).not.toBeNull();
    expect(placeholder(glyph.container, 16)).not.toBeNull();
    await waitFor(() => expect(placeholder(avatar.container, 32)).toBeNull(), { timeout: 10000 });
    await waitFor(() => expect(placeholder(glyph.container, 16)).toBeNull());
    // Drawn again, it is there at once.
    expect(placeholder(render(<Glyph size={16} />).container, 16)).toBeNull();
}, 20000);
