// Every path no other route takes: a 404, shown by the root's error boundary. It exists so the gate runs for these
// paths too (see routes.ts).
import { data } from 'react-router';

export function loader() {
    throw data(null, { status: 404 });
}

// Never rendered: the loader always throws. A route with a component is a page, so the 404 is shown as one.
export default function NotFound() {
    return null;
}
