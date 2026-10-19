// The landing hero: the statement and calls to action, and with them the "Text NoClick" card. WhatsApp is the default; each app's code and links open NoClick's number for it with a
// greeting drafted, and the switch moves between them.
import { nc } from '~/lib/nc';

const WHATSAPP_LINK = 'https://wa.me/14242421064?text=Hi%20NoClick!';
const IMESSAGE_LINK = 'sms:+16126493126&body=Hi%20NoClick!';

export default async function () {
    nc.assert.equal(window.location.pathname, '/', 'Open the landing page before running this test');

    const hero = await nc.wait.forElement('[data-testid="launchpad-hero"]');
    const heading = hero.querySelector('h1') as HTMLElement;
    nc.assert.equal(
        Array.from(heading.children)
            .map((line) => line.textContent?.trim())
            .join(' '),
        'Run a business from your phone.',
        'The hero keeps the approved headline'
    );
    nc.assert.truthy(getComputedStyle(heading).fontFamily.includes('Instrument Serif'), 'The hero uses the display serif');

    const actions = hero.querySelector('[data-testid="launchpad-hero-actions"]') as HTMLElement;
    nc.assert.truthy((actions.textContent ?? '').includes('Start free'), 'The primary CTA stays');
    nc.assert.truthy((actions.textContent ?? '').includes('Book a demo'), 'The demo link stays');
    nc.assert.truthy(actions.getBoundingClientRect().top >= heading.getBoundingClientRect().bottom, 'The CTAs sit below the title');

    nc.assert.equal(document.querySelectorAll('[data-testid="space-hero-art"], .space-hero__galaxy-picture').length, 0, 'The galaxy is gone');
    nc.assert.equal(
        Array.from(document.querySelectorAll('img')).filter((img) => img.src.includes('/space-hero/')).length,
        0,
        'No galaxy image is requested'
    );

    const card = hero.querySelector('[data-testid="text-noclick-card"]') as HTMLElement;
    nc.assert.truthy(card, 'The Text NoClick card stands in the galaxy’s place');
    const tabs = Array.from(card.querySelectorAll<HTMLButtonElement>('[role="radio"]'));
    nc.assert.equal(tabs.map((t) => t.textContent?.trim()).join(','), 'WhatsApp,iMessage', 'The switch offers WhatsApp and iMessage');
    // The visitor's likelier app comes first; pick WhatsApp so the rest of the test starts from it.
    tabs[0].click();
    await nc.wait.until(() => tabs[0].getAttribute('aria-checked') === 'true', 2000);

    const qr = card.querySelector('[role="img"][aria-label="Scan to text NoClick on WhatsApp"]');
    nc.assert.truthy(qr, 'WhatsApp shows a code to scan');
    nc.assert.equal(card.querySelector('[data-testid="text-noclick-open"]')?.textContent?.trim(), 'Open WhatsApp', 'A button under the code opens WhatsApp');
    const links = Array.from(card.querySelectorAll<HTMLAnchorElement>('a[href]'));
    nc.assert.truthy(links.length > 0 && links.every((a) => a.href === WHATSAPP_LINK), 'Every way to open the chat goes to NoClick’s WhatsApp with a greeting drafted');

    // Tapped, the code opens full screen for someone else to scan, and a tap anywhere closes it.
    (card.querySelector('button[aria-label$="show the code full screen"]') as HTMLButtonElement).click();
    const enlarged = await nc.wait.forElement('[role="dialog"]');
    nc.assert.truthy(enlarged.querySelector('[role="img"][aria-label="Scan to text NoClick on WhatsApp"]'), 'The full-screen code is the same code');
    nc.assert.truthy(enlarged.querySelector('[role="img"]')!.getBoundingClientRect().width > (qr as HTMLElement).getBoundingClientRect().width, 'Full screen, the code is bigger');
    (enlarged as HTMLElement).click();
    await nc.wait.until(() => !document.querySelector('[role="dialog"]'), 2000);

    tabs[1].click();
    await nc.wait.until(() => tabs[1].getAttribute('aria-checked') === 'true', 2000);
    nc.assert.truthy(card.querySelector('[role="img"][aria-label="Scan to text NoClick on iMessage"]'), 'iMessage shows its own code to scan');
    const imessageLinks = Array.from(card.querySelectorAll<HTMLAnchorElement>('a[href]'));
    nc.assert.truthy(imessageLinks.length > 0 && imessageLinks.every((a) => a.getAttribute('href') === IMESSAGE_LINK), 'iMessage opens Messages on NoClick’s line with a greeting drafted');
    nc.assert.truthy((card.textContent ?? '').includes('Open Messages'), 'iMessage opens the Messages app');

    tabs[0].click();
    await nc.wait.until(() => tabs[0].getAttribute('aria-checked') === 'true', 2000);
    nc.assert.truthy(card.querySelector('[role="img"][aria-label="Scan to text NoClick on WhatsApp"]'), 'The switch goes back to WhatsApp');

    nc.assert.truthy(document.documentElement.scrollWidth <= window.innerWidth, 'The hero causes no horizontal overflow');
    return { qr: !!qr, links: links.length };
}
