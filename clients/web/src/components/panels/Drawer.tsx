import type { ReactNode } from "react";

export function Drawer({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  return (
    <>
      <div
        style={{ position: "fixed", inset: 0, zIndex: 44 }}
        onClick={onClose}
      />
      <aside className="drawer">
        <div className="drawer-head">
          {title}
          <div className="header-spacer" />
          <button className="icon-btn" onClick={onClose} title="Close (Esc)">
            ✕
          </button>
        </div>
        <div className="drawer-body">{children}</div>
      </aside>
    </>
  );
}
