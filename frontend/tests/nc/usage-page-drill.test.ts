// Settings → Usage on a signed-in account with charges this period: drills into AI models, into a model and onto
// what used it, picks one, and climbs back out a level at a time, then picks a day, checking each time that the URL,
// the breadcrumb and the charges table follow. Throws on the first thing that doesn't; returns what it saw.
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function until<T>(what: string, read: () => T | null | undefined | false, ms = 8000): Promise<T> {
    const end = Date.now() + ms;
    for (;;) {
        const v = read();
        if (v) return v;
        if (Date.now() > end) throw new Error(`timed out waiting for ${what}`);
        await wait(50);
    }
}

const where = () => document.querySelector<HTMLElement>('section[aria-label="Where it goes"]');
const charges = () => document.querySelector<HTMLElement>('section[aria-label="Charges"]');
const count = () => Number((charges()?.querySelector('h3 span')?.textContent ?? '').split('·')[0].replace(/[^\d]/g, ''));
const rows = () => Array.from(charges()?.querySelectorAll<HTMLElement>('[role="row"][tabindex="0"]') ?? []);
const days = () => Array.from(charges()?.querySelectorAll('[role="rowgroup"] > [role="row"] > span:first-child') ?? []).map((s) => s.textContent ?? '');
const param = (k: string) => new URLSearchParams(location.search).get(k);
const idle = () => !charges()?.querySelector('[aria-busy="true"]');
const listRows = () => Array.from(where()?.querySelectorAll<HTMLElement>('[role="button"]') ?? []);
const crumbs = () => Array.from(where()?.querySelectorAll('nav[aria-label="Where it goes, drilled"] li') ?? []).map((li) => li.textContent ?? '');
const rowNamed = (name: string) => Array.from(where()?.querySelectorAll<HTMLElement>('[role="button"]') ?? []).find((r) => r.textContent?.includes(name));

export default async function () {
    window.dispatchEvent(new CustomEvent('noclick:switch-tab', { detail: { tab: 'settings', section: 'usage' } }));
    await until('the usage page', () => where() && charges() && rows().length > 0, 20000);
    const seen: Record<string, unknown> = { all: count() };

    // In: AI models opens onto its models, and the charges are only theirs.
    const ai = await until('the AI models row', () => rowNamed('AI models'));
    ai.click();
    await until('the drilled breadcrumb', () => where()?.querySelector('nav[aria-label="Where it goes, drilled"]'));
    if (param('in') !== 'service:ai') throw new Error(`in=${param('in')}`);
    await until('narrowed charges', () => count() < (seen.all as number) && !charges()?.querySelector('[aria-busy="true"]'));
    seen.ai = count();
    const services = rows().map((r) => r.textContent ?? '');
    seen.firstRows = services.slice(0, 3);

    // A model opens onto what used it, and narrows the charges to the model.
    await until('the models', () => where()?.textContent?.includes('By model'));
    await wait(700); // the level settles
    const model = await until('a model row', () => listRows().find((r) => !r.textContent?.includes('NoClick’s own model')));
    const modelName = model.querySelector('span')?.textContent ?? '';
    model.click();
    await until('the model in the URL', () => param('in')?.startsWith('service:ai,item:'));
    await until('what used it', () => where()?.textContent?.includes('By what used it'));
    await until('charges for the model', () => idle() && count() <= (seen.ai as number) && rows().every((r) => r.textContent?.includes(modelName)));
    seen.model = { name: modelName, charges: count() };

    // What used it narrows them to its own, and rides the URL.
    await wait(700);
    const consumer = await until('a row of what used it', () => Array.from(where()?.querySelectorAll<HTMLElement>('[role="button"][aria-pressed]') ?? [])[0]);
    const consumerName = consumer.querySelector('span')?.textContent ?? '';
    consumer.click();
    await until('pick in the URL', () => param('pick'));
    await until('charges for what used it', () => idle() && count() <= (seen.model as { charges: number }).charges && rows().every((r) => r.textContent?.includes(modelName) && r.textContent?.includes(consumerName)));
    seen.consumer = { name: consumerName, charges: count(), crumbs: crumbs() };

    // Out: Escape climbs one level at a time, back to every charge.
    const escape = () => where()!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    escape();
    await until('the pick cleared', () => !param('pick') && param('in')?.includes('item:'));
    escape();
    await until('back at the models', () => param('in') === 'service:ai');
    escape();
    await until('the drill cleared', () => !param('in') && !where()?.querySelector('nav[aria-label="Where it goes, drilled"]'));
    await until('every charge again', () => count() === seen.all);

    // A day: the charges are that day's, under one heading.
    const day = await until('a day with spend', () => {
        const bars = Array.from(document.querySelectorAll<SVGRectElement>('rect[data-day].cursor-pointer'));
        return bars.length ? bars[bars.length - 1] : null;
    });
    day.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await until('one day of charges', () => days().length === 1 && charges()?.textContent?.includes('×') !== undefined);
    seen.day = { picked: day.getAttribute('data-day'), heading: days()[0], charges: count() };
    if (count() >= (seen.all as number)) throw new Error('the day did not narrow the charges');
    return seen;
}
