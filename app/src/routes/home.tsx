// The app's one page until its screens move in: what the app is, and where the SDK it runs on is documented.
import { VERSION } from 'noclick';
import { PAGE_TITLE } from '@/ui/titles';
import type { Route } from './+types/home';

export const meta: Route.MetaFunction = () => [
    { title: 'NoClick' },
    { name: 'description', content: 'NoClick’s app, built on its TypeScript SDK.' },
];

export default function Home() {
    return (
        <main className="mx-auto flex min-h-screen max-w-xl flex-col justify-center gap-4 px-6 py-16 leading-relaxed">
            <h1 className={PAGE_TITLE}>NoClick</h1>
            <p>
                This is NoClick’s app: the screens for working with a NoClick account, built only on the TypeScript SDK
                (<code>noclick</code> {VERSION}).
            </p>
            <p>Its screens are moving in one at a time. Until the first arrives, this page is all it has.</p>
            <p>
                <a className="underline underline-offset-4" href="https://noclick.com/docs">
                    Read the SDK docs
                </a>
            </p>
        </main>
    );
}
