import createClient from "openapi-fetch";
import type { paths, components } from "../../../packages/api-client/schema";

export type Schemas = components["schemas"];
export type Work = Schemas["WorkOut"];
export type Draft = Schemas["DraftOut"];
export type Member = Schemas["MemberOut"];
export type Department = Schemas["DepartmentOut"];
export type Initiative = Schemas["InitiativeOut"];
export type Evidence = Schemas["EventOut"];
export type Dashboard = Schemas["DashboardOut"];
export type Me = Schemas["MeOut"];
export type MembershipContext = Schemas["MembershipContext"];
export type ProposedFields = Schemas["ProposedFields"];

export function api(organizationId?: string) {
  return createClient<paths>({
    baseUrl: "",
    credentials: "same-origin",
    headers: {
      "X-CoRoof-Request": "1",
      ...(organizationId ? { "X-Organization-Id": organizationId } : {}),
    },
  });
}

export function unwrap<T>(result: { data?: T; error?: unknown }): T {
  if (result.error || result.data === undefined) {
    const value = result.error as { error?: { message?: string } } | undefined;
    throw new Error(value?.error?.message || "连接失败，请稍后重试。");
  }
  return result.data;
}

export const statusLabels: Record<Work["lifecycle_status"], string> = {
  planned: "未开始",
  in_progress: "进行中",
  done: "已完成",
  cancelled: "已取消",
};

export function formatTime(
  value: string | null | undefined,
  timezone = "Asia/Shanghai",
) {
  if (!value) return "尚无记录";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: timezone,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}
