// A delete made with the pointer (a step's delete pill), told apart from one made from the keyboard. The post-delete
// selection-move autopan is helpful for keyboard deletes (the person's focus follows the selection) but distracting for
// pointer deletes (the pointer is already where they're looking): the pill marks its deletes here, and the canvas's
// remove handler consumes the mark, keeping the selection move while skipping the pan.

let pointerDeleteAt = 0;

export function markPointerDrivenDelete(): void {
    pointerDeleteAt = Date.now();
}

export function consumePointerDrivenDelete(): boolean {
    const recent = Date.now() - pointerDeleteAt < 500;
    pointerDeleteAt = 0;
    return recent;
}
