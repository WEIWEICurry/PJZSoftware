import Workspace from "../../src/workspace";
export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <Workspace />
      {children}
    </>
  );
}
