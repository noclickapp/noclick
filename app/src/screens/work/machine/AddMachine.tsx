// Adding a machine from Resources' Machines: one Add machine that opens both ways and what each costs (renting one from
// NoClick, from its cheapest size's price a month, or using a computer of yours, free), then slides into the one picked:
// the machine-buying dialog with no agent (renting it for the account), or Add your computer unchanged. An empty
// Machines shows the same two choices in place of a button, and a pick there opens Add machine on that way, held above
// the list so it stays up once the new machine fills it.
import { useState, type ReactNode } from 'react';
import { ChevronRight, Laptop, Plus, Server } from 'lucide-react';
import { ShellDialog } from '@/ui/ShellDialog';
import { cn } from '@/ui/utils';
import { AddComputer } from './AddComputer';
import { BuyMachine } from './BuyMachine';
import { sizeChoices } from './offers';
import { useMachineSizes } from './reads';

type Way = 'choose' | 'rent' | 'own';

/** The cheapest size worth buying now, a month: what renting one starts from. */
function useFromPrice(): number | null {
    const sizes = useMachineSizes().data;
    const from = sizeChoices(sizes ?? [])
        .map((c) => c.from)
        .filter((n): n is number => n !== null);
    return from.length ? Math.min(...from) : null;
}

/** The two ways, as rows: each says what it is and what it costs. */
export function MachineWays({
    onPick,
    className,
}: {
    onPick: (way: 'rent' | 'own') => void;
    className?: string;
}) {
    const from = useFromPrice();
    const row = (
        way: 'rent' | 'own',
        icon: ReactNode,
        title: string,
        line: string,
        price: string
    ) => (
        <button
            key={way}
            type="button"
            onClick={() => onPick(way)}
            data-testid={`machine-way-${way}`}
            className="flex w-full items-center gap-3 rounded-[20px] px-3.5 py-3 text-left ring-1 ring-inset ring-border transition-colors hover:bg-foreground/[0.03] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring dark:ring-foreground/[0.1]"
        >
            <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-foreground/[0.06]">
                {icon}
            </span>
            {/* On a phone the price goes under the words, which keep the row's width. */}
            <span className="flex min-w-0 flex-1 flex-col gap-1 sm:flex-row sm:items-center sm:gap-3">
                <span className="grid min-w-0 flex-1 gap-px">
                    <span className="text-[14px] font-medium">{title}</span>
                    <span className="text-[12.5px] leading-snug text-muted-foreground">
                        {line}
                    </span>
                </span>
                <span className="text-[12.5px] font-medium tabular-nums text-foreground/85 sm:shrink-0 sm:text-right">
                    {price}
                </span>
            </span>
            <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
        </button>
    );
    return (
        <div className={cn('grid gap-1.5', className)}>
            {row(
                'rent',
                <Server
                    className="h-4 w-4 text-foreground/75"
                    strokeWidth={1.75}
                />,
                'Rent one from NoClick',
                'Always on, run by NoClick, sold at cost.',
                from !== null
                    ? `From $${from.toFixed(2)} a month`
                    : 'A monthly price'
            )}
            {row(
                'own',
                <Laptop
                    className="h-4 w-4 text-foreground/75"
                    strokeWidth={1.75}
                />,
                'Use your own computer or server',
                'Agents work on it while it’s on.',
                'Free'
            )}
        </div>
    );
}

/** Whichever way was picked, as its own dialog; `onDone` takes the machine to open, or null. */
function WayDialog({
    way,
    onBack,
    onDone,
}: {
    way: 'rent' | 'own';
    onBack: () => void;
    onDone: (id: string | null) => void;
}) {
    if (way === 'rent')
        return (
            <BuyMachine
                onBought={() => undefined}
                onOpen={(machine) => onDone(machine.id)}
                onClose={() => onDone(null)}
                back={{ label: 'Add a machine', onBack }}
            />
        );
    return (
        <AddComputer
            use={{ label: 'Open it', onUse: (computer) => onDone(computer.id) }}
            onClose={(computer) => onDone(computer?.id ?? null)}
        />
    );
}

/** Add machine's popup: both ways, then the one picked (`way`, where it opens on one picked already). */
export function AddMachine({
    onDone,
    way: start,
}: {
    onDone: (id: string | null) => void;
    way?: string;
}) {
    const [way, setWay] = useState<Way>(
        start === 'rent' || start === 'own' ? start : 'choose'
    );
    if (way !== 'choose')
        return (
            <WayDialog
                way={way}
                onBack={() => setWay('choose')}
                onDone={onDone}
            />
        );
    return (
        <ShellDialog
            open
            onOpenChange={(open) => !open && onDone(null)}
            title="Add a machine"
            description="Where your agents work. Your account can have both."
            mark={<Plus className="h-5 w-5" strokeWidth={1.75} />}
            testId="add-machine"
        >
            <MachineWays onPick={setWay} className="pb-4" />
        </ShellDialog>
    );
}

/** An empty Machines: the two ways in place of a button; a pick opens Add machine on it. */
export function MachineChoices({
    onPick,
}: {
    onPick: (way: 'rent' | 'own') => void;
}) {
    return (
        <MachineWays
            onPick={onPick}
            className="mt-5 w-full max-w-md text-left"
        />
    );
}
