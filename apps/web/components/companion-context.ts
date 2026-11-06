import type { Work } from "../lib/api";

/** Shared factual selection for both companion presentations. */
export function companionContext(works: Work[], now: number) {
  const active = works.filter(
    (work) => !["done", "cancelled"].includes(work.lifecycle_status),
  );
  const native = active.filter((work) => work.source_authority === "native");
  const support = native.filter((work) => work.needs_support);
  const overdue = native.filter(
    (work) => work.due_at && new Date(work.due_at).getTime() < now,
  );
  const unassigned = native.filter((work) => !work.owner_id);
  const reason = support.length
    ? "support"
    : overdue.length
      ? "overdue"
      : unassigned.length
        ? "unassigned"
        : "latest";
  const candidates = support.length
    ? support
    : overdue.length
      ? overdue
      : unassigned.length
        ? unassigned
        : active;
  const focus = [...candidates].sort(
    (a, b) =>
      new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime() ||
      a.id.localeCompare(b.id),
  )[0];
  const explanation =
    reason === "support"
      ? "依据：工作记录明确标记了支持需求。先核实需要谁协作，以及还缺什么。"
      : reason === "overdue"
        ? "依据：事项尚未结束，且已过记录中的截止时间。实际交付结果仍需核实。"
        : reason === "unassigned"
          ? "依据：工作尚未指定负责人。可以先讨论分工，再由有权限的人确认。"
          : focus?.source_authority === "external"
            ? "这是一条外部同步记录，实际支持需求与交付情况仍需核实。"
            : "这是当前范围内最近更新的进行或待开始事项，不能据此判断整体运行状况。";
  const question = focus
    ? `请核实「${focus.title}」的${reason === "support" ? "支持需求和协作缺口" : reason === "overdue" ? "截止时间与实际交付记录" : reason === "unassigned" ? "分工与责任范围" : "最近进展和待补充信息"}，给出有依据的下一步建议。缺失信息保持未知，不代替同事确认进展。`
    : "当前工作记录还不足，请先检查已有资料与信息缺口，说明需要补充什么；不要假设项目、人员分工或经营成果。";
  return {
    active,
    support,
    overdue,
    unassigned,
    reason,
    focus,
    explanation,
    question,
  };
}
