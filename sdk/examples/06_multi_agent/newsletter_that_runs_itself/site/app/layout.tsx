import type { ReactNode } from "react";
import { PUBLICATION } from "../lib/noclick";

export const metadata = { title: PUBLICATION.name, description: PUBLICATION.tagline };

export default function Layout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body style={{ maxWidth: 640, margin: "48px auto", padding: "0 16px", font: "18px/1.6 Georgia, serif" }}>
        {children}
      </body>
    </html>
  );
}
