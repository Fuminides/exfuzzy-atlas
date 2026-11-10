import { tr } from "../i18n";

export function SyntheticBanner({ show }: { show: boolean }) {
  if (!show) return null;
  return (
    <div className="banner" role="status">
      <strong>{tr("DATOS SINTÉTICOS. No son mediciones reales.", "SYNTHETIC DATA. These aren't real measurements.")}</strong>{" "}
      {tr("La API marca estos datos como sintéticos (fixtures o un modelo de prueba). Ninguna estación, valor o regla corresponde a datos reales.", "The API marks these data as synthetic (fixtures or a test model). No station, value or rule comes from real data.")}
    </div>
  );
}
