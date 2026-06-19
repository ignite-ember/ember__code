import { useEffect, type ReactNode } from "react";
import { CloseIcon } from "../Icons";

export function Drawer({
  title,
  headerExtras,
  toolbar,
  onClose,
  children,
}: {
  title: ReactNode;
  /** Slot rendered between the title and the close button — sized
   *  to the remaining horizontal space. Used for inline search,
   *  status pills, etc. */
  headerExtras?: ReactNode;
  /** Optional non-scrolling row docked under the header (filters,
   *  status counts). Sits outside the scrollable body so list
   *  items can never peek above it. */
  toolbar?: ReactNode;
  onClose: () => void;
  children: ReactNode;
}) {
  // The close button advertises "Close (Esc)" — honor it. Capture
  // phase + stopPropagation so the app-level Esc (cancel run) doesn't
  // also fire while a panel is open.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      // A file preview (or any overlay marked .modal-overlay) sits
      // ON TOP of the drawer and owns Esc while it's open — don't
      // close the drawer underneath it.
      if (document.querySelector(".file-preview, .modal-overlay")) return;
      e.stopPropagation();
      onClose();
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onClose]);

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className="drawer">
        <div className="drawer-head">
          {title}
          {headerExtras ? (
            <div className="drawer-head-extras">{headerExtras}</div>
          ) : (
            <div className="header-spacer" />
          )}
          <button className="icon-btn" onClick={onClose} title="Close (Esc)">
            <CloseIcon />
          </button>
        </div>
        {toolbar && <div className="drawer-toolbar">{toolbar}</div>}
        <div className="drawer-body">{children}</div>
      </aside>
    </>
  );
}
