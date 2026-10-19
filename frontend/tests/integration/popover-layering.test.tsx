// A popover opened inside the phone menu or a dialog sits on top of it. The usage popover once opened behind the
// menu sheet, so its Add funds button was there but no tap could reach it.
import type { ReactNode } from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { userEvent } from '@vitest/browser/context';
import * as RadixDialog from '@radix-ui/react-dialog';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '~/components/ui/dialog';
import { Popover, PopoverContent, PopoverTrigger } from '~/components/ui/popover';
import { SIDEBAR_SHEET, SIDEBAR_SHEET_OVERLAY } from '~/components/shell/AppSidebar';

afterEach(cleanup);

function Usage({ onAddFunds }: { onAddFunds: () => void }) {
    return (
        <Popover>
            <PopoverTrigger>Usage</PopoverTrigger>
            <PopoverContent side="top">
                <button type="button" onClick={onAddFunds}>
                    Add funds
                </button>
            </PopoverContent>
        </Popover>
    );
}

const PhoneMenu = ({ children }: { children: ReactNode }) => (
    <RadixDialog.Root open>
        <RadixDialog.Portal>
            <RadixDialog.Overlay className={SIDEBAR_SHEET_OVERLAY} />
            <RadixDialog.Content className={SIDEBAR_SHEET}>
                <RadixDialog.Title>Menu</RadixDialog.Title>
                <RadixDialog.Description>Pages and your account</RadixDialog.Description>
                <div className="absolute inset-x-2 bottom-4">{children}</div>
            </RadixDialog.Content>
        </RadixDialog.Portal>
    </RadixDialog.Root>
);

const AppDialog = ({ children }: { children: ReactNode }) => (
    <Dialog open>
        <DialogContent>
            <DialogTitle>Settings</DialogTitle>
            <DialogDescription>A dialog with a popover in it</DialogDescription>
            {children}
        </DialogContent>
    </Dialog>
);

it.each([
    ['the phone menu', PhoneMenu],
    ['a dialog', AppDialog],
])('a popover opened in %s takes the tap', async (_, Surface) => {
    const onAddFunds = vi.fn();
    render(
        <Surface>
            <Usage onAddFunds={onAddFunds} />
        </Surface>
    );

    await userEvent.click(screen.getByRole('button', { name: 'Usage' }));
    const addFunds = await screen.findByRole('button', { name: 'Add funds' });
    const box = addFunds.getBoundingClientRect();
    expect(document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2)).toBe(addFunds);

    await userEvent.click(addFunds);
    expect(onAddFunds).toHaveBeenCalledOnce();
});
