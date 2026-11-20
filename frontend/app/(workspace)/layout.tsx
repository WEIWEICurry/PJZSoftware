import { Suspense } from "react";
import { StartupScreen } from "../../src/startup-screen";
import Workspace from "../../src/workspace";
export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <Suspense fallback={<StartupScreen error="" />}>
        <Workspace />
      </Suspense>
      {children}
    </>
  );
}
