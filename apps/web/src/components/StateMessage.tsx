import { tr } from "../i18n";

export function StateMessage({
  kind,
  children,
  onRetry,
}: {
  kind: "loading" | "empty" | "error";
  children: React.ReactNode;
  onRetry?: () => void;
}) {
  return (
    <div className={`state state--${kind}`} role={kind === "error" ? "alert" : "status"}>
      <p>{children}</p>
      {kind === "error" && onRetry && (
        <button type="button" onClick={onRetry}>
          {tr("Reintentar", "Retry")}
        </button>
      )}
    </div>
  );
}
