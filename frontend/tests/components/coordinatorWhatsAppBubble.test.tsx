// @vitest-environment jsdom
// The WhatsApp bubble in the coordinator chat: a shared contact or place drawn as WhatsApp draws it, and the corner's
// time and read ticks only together.
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { WhatsAppMessage } from '~/components/coordinator/inline/channels';

afterEach(cleanup);

it('draws a shared contact with its number and a way to message it', () => {
    render(
        <WhatsAppMessage
            time="12:38 PM"
            shared={[{ kind: 'contact', contact: { name: 'Priya Shah', phones: [{ number: '+1 415 555 0177', waId: '14155550177' }], emails: [] } }]}
        />
    );
    expect(screen.getByText('Priya Shah')).toBeTruthy();
    expect(screen.getByText('+1 415 555 0177')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Message' }).getAttribute('href')).toBe('https://wa.me/14155550177');
    expect(screen.getByText('12:38 PM')).toBeTruthy();
});

it('opens a shared place in Maps', () => {
    render(<WhatsAppMessage shared={[{ kind: 'place', place: { latitude: 37.7764, longitude: -122.4241, name: 'Blue Bottle Coffee' } }]} />);
    const link = screen.getByRole('link', { name: /Blue Bottle Coffee/ });
    expect(link.getAttribute('href')).toBe('https://www.google.com/maps/search/?api=1&query=37.7764%2C-122.4241');
});

it('shows no read ticks for a turn saved without a time', () => {
    const { container } = render(<WhatsAppMessage text="Hey" />);
    expect(screen.getByText('Hey')).toBeTruthy();
    expect(container.querySelector('.lucide-check-check')).toBeNull();
    cleanup();
    const timed = render(<WhatsAppMessage text="Hey" time="9:41 AM" />);
    expect(timed.container.querySelector('.lucide-check-check')).not.toBeNull();
});
