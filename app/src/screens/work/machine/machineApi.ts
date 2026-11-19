// What a machine's own page does through the platform client: open a shell on the machine (`machine.shell()`, opened
// at the same terminal websocket a sandbox's shell is), list a folder of its disk (`machine.files.list`), read and write
// one file (`machine.files`), and start, stop or restart it, each saying how it went.
import { toast } from 'sonner';
import {
    Machine,
    TerminalConnection,
    type NoClick,
    type TerminalConnectOptions,
} from 'noclick';
import type { MachineView } from './machineView';
import { rereadMachine } from './reads';
import type { OpenedShell } from './ShellDrawer';

/** Where a machine's own files are listed from: its user's home. */
export const MACHINE_HOME = '/home/noclick';
/** The most one file can be to read or download here (the API's cap). */
export const MACHINE_FILE_MAX = 16 * 1024 * 1024;

export interface MachineEntry {
    path: string;
    type: 'file' | 'directory';
    size: number | null;
    updatedAt: string | null;
}

const machineOf = (client: NoClick, machineId: string, user: string | null) =>
    Machine.fromId(machineId, { client, user });

/** A single-use shell token for the machine, and the connection it opens once. */
export async function openMachineShell(
    client: NoClick,
    machineId: string,
    user: string | null
): Promise<OpenedShell> {
    const shell = await machineOf(client, machineId, user).shell();
    let used = false;
    return {
        token: shell.token,
        connect(options: TerminalConnectOptions = {}) {
            if (used)
                throw new TypeError(
                    'A shell token opens it once: ask for another.'
                );
            used = true;
            // Asked while it's open, a new shell token renews it in place: bash goes on.
            const renew = async () =>
                (await machineOf(client, machineId, user).shell()).token;
            return new TerminalConnection(shell.url, shell.token, {
                ...options,
                renew: options.renew ?? renew,
            });
        },
    };
}

/** One folder's entries (every page of it), folders first, then by name. */
export async function listMachineFiles(
    client: NoClick,
    machineId: string,
    user: string | null,
    path: string
): Promise<{ path: string; entries: MachineEntry[] }> {
    const listed = await machineOf(client, machineId, user).files.list(path);
    const entries = listed.map((e) => ({
        path: e.path,
        type: e.type,
        size: e.size,
        updatedAt: e.updatedAt ? e.updatedAt.toISOString() : null,
    }));
    entries.sort((a, b) =>
        a.type === b.type
            ? a.path.localeCompare(b.path)
            : a.type === 'directory'
              ? -1
              : 1
    );
    return { path, entries };
}

export const machineFiles = (
    client: NoClick,
    machineId: string,
    user: string | null
) => machineOf(client, machineId, user).files;

/** Start, stop or restart it, saying how it went. */
export async function powerAction(
    client: NoClick,
    view: MachineView,
    action: 'start' | 'stop' | 'restart'
): Promise<void> {
    const machine = machineOf(client, view.id, view.userId);
    try {
        if (action === 'start') await machine.start();
        else if (action === 'stop') await machine.stop();
        else await machine.restart();
        toast(
            action === 'start'
                ? `${view.name} is starting`
                : action === 'stop'
                  ? `${view.name} stopped`
                  : `${view.name} is restarting`,
            {
                description:
                    action === 'start'
                        ? 'Agents can work on it again in about 3 minutes.'
                        : action === 'stop'
                          ? `Agents wait until you start it. It’s still charged each day.`
                          : 'What agents were doing stopped; they pick up with their next message.',
            }
        );
    } catch (error) {
        toast(`Couldn’t ${action} ${view.name}`, {
            description: error instanceof Error ? error.message : String(error),
        });
    } finally {
        rereadMachine(view.id);
    }
}
