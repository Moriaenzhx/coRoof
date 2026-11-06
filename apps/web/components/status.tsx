import {
  CircleAlert,
  CircleCheck,
  CircleHelp,
  CircleSlash,
  Clock3,
  FileText,
  LoaderCircle,
  TriangleAlert,
} from "lucide-react";
import type { ReactNode } from "react";
import { statusLabels, type Dashboard, type Work } from "../lib/api";

type Status = Work["lifecycle_status"] | "support" | "unknown" | "recorded";

const statuses = {
  planned: { label: statusLabels.planned, Icon: Clock3 },
  in_progress: { label: statusLabels.in_progress, Icon: LoaderCircle },
  done: { label: statusLabels.done, Icon: CircleCheck },
  cancelled: { label: statusLabels.cancelled, Icon: CircleSlash },
  support: { label: "需要支持", Icon: TriangleAlert },
  unknown: { label: "未知 / 无数据", Icon: CircleHelp },
  recorded: { label: "已有记录", Icon: FileText },
} satisfies Record<Status, { label: string; Icon: typeof Clock3 }>;

// Coverage describes available facts, never an inferred health assessment.
export function departmentStatus(department: Dashboard["departments"][number]) {
  return department.support_count > 0
    ? "support"
    : department.coverage === "unknown"
      ? "unknown"
      : "recorded";
}

export function StatusIcon({
  status,
  size = 14,
}: {
  status: Status;
  size?: number;
}) {
  const Icon = statuses[status].Icon;
  return <Icon size={size} aria-hidden="true" />;
}

export function StatusLabel({
  status,
  children,
  variant = "badge",
}: {
  status: Status;
  children?: ReactNode;
  variant?: "badge" | "inline";
}) {
  return (
    <span className={`status-label status-${variant}`} data-status={status}>
      <StatusIcon status={status} />
      <span>{children ?? statuses[status].label}</span>
    </span>
  );
}

export function Feedback({
  kind,
  children,
}: {
  kind: "error" | "success" | "info";
  children: ReactNode;
}) {
  const Icon =
    kind === "error" ? CircleAlert : kind === "info" ? CircleHelp : CircleCheck;
  return (
    <div
      className={`feedback ${kind}`}
      role={kind === "error" ? "alert" : "status"}
    >
      <Icon size={17} aria-hidden="true" />
      <div>{children}</div>
    </div>
  );
}
