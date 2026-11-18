// @vitest-environment happy-dom
import { cleanup, render, screen } from '@testing-library/react';
import { VERSION } from 'noclick';
import { afterEach, expect, it } from 'vitest';
import Home from './home';

afterEach(cleanup);

it('names the SDK it runs on, from the SDK itself, and links its docs', () => {
    render(<Home />);
    expect(screen.getByRole('heading', { name: 'NoClick' })).toBeTruthy();
    expect(screen.getByText(/built only on the TypeScript SDK/).textContent).toContain(`noclick ${VERSION}`);
    expect(screen.getByRole('link', { name: 'Read the SDK docs' }).getAttribute('href')).toBe('https://noclick.com/docs');
});
