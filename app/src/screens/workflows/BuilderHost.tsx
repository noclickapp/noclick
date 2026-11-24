// The builder beside a workflow's page, as the app's frame draws it: whatever stands in the canvas's `canvas.builder`
// slot (its standard starts a build with NoClick's builder and shows how it goes). Loaded with the first workflow
// opened, so the frame's other pages load none of the canvas's slots.
import { useSlot } from '@/slots';
import { BUILDER, type CanvasBuilderProps } from '@/screens/canvas/slots';

export default function BuilderHost(props: CanvasBuilderProps) {
    const Builder = useSlot(BUILDER);
    return <Builder {...props} />;
}
