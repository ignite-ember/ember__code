export interface PickerEntry {
  key: string;
  label: string;
  detail?: string;
  current?: boolean;
}

export function Picker({
  entries,
  onPick,
  onClose,
}: {
  entries: PickerEntry[];
  onPick: (key: string) => void;
  onClose: () => void;
}) {
  return (
    <>
      <div style={{ position: "fixed", inset: 0, zIndex: 30 }} onClick={onClose} />
      <div className="picker">
        {entries.length === 0 && <div className="picker-item dim">No entries</div>}
        {entries.map((e) => (
          <div
            key={e.key}
            className={`picker-item${e.current ? " current" : ""}`}
            onClick={() => onPick(e.key)}
          >
            <span>{e.label}</span>
            {e.detail && <span className="dim">{e.detail}</span>}
          </div>
        ))}
      </div>
    </>
  );
}
