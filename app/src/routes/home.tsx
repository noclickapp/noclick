// The signed-in owner's home: their NoClick account at a glance.
import { AccountScreen } from '@/screens/account/AccountScreen';
import type { Route } from './+types/home';

export const meta: Route.MetaFunction = () => [
    { title: 'NoClick' },
    { name: 'description', content: 'NoClick’s app, built on its TypeScript SDK.' },
];

export default function Home() {
    return <AccountScreen />;
}
