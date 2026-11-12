import { ArrowUpRight } from "lucide-react";
export function PageTitle({
  eyebrow,
  title,
  detail,
  action: button,
}: {
  eyebrow: string;
  title: string;
  detail: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="page-title">
      <div>
        <div className="eyebrow">{eyebrow}</div>
        <h1>{title}</h1>
        <p>{detail}</p>
      </div>
      {button}
    </div>
  );
}
export function Empty({
  icon,
  title,
  copy,
  button,
  onClick,
}: {
  icon: React.ReactNode;
  title: string;
  copy: string;
  button?: string;
  onClick?: () => void;
}) {
  return (
    <div className="empty-state">
      <span>{icon}</span>
      <strong>{title}</strong>
      <p>{copy}</p>
      {button && (
        <button className="button-quiet" onClick={onClick}>
          {button} <ArrowUpRight size={14} />
        </button>
      )}
    </div>
  );
}
