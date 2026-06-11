import { useRef, useState } from "react";

/**
 * Auto-growing prompt input. Enter submits, Shift+Enter inserts a
 * newline (webview convention — friendlier than the TUI's \+Enter).
 */
export function PromptInput({
  disabled,
  placeholder,
  onSubmit,
}: {
  disabled: boolean;
  placeholder: string;
  onSubmit: (text: string) => void;
}) {
  const [text, setText] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  const autoGrow = () => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 220)}px`;
  };

  const submit = () => {
    const t = text.trim();
    if (!t) return;
    setText("");
    requestAnimationFrame(autoGrow);
    onSubmit(t);
  };

  return (
    <textarea
      ref={ref}
      className="prompt-input"
      rows={1}
      value={text}
      disabled={disabled}
      placeholder={placeholder}
      onChange={(e) => {
        setText(e.target.value);
        autoGrow();
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          submit();
        }
      }}
    />
  );
}
