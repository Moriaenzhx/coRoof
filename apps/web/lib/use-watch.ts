"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, unwrap, type Schemas } from "./api";
import { useVisibleRefresh } from "./use-visible-refresh";

type WatchData = {
  scope: string;
  policies: Schemas["WatchPolicyOut"][];
  items: Schemas["AttentionOut"][];
  error: string;
  loading: boolean;
};

/** A display gate only; the server still authorizes every watch read. */
export function useWatch(
  organizationId: string,
  history = false,
  enabled = true,
) {
  const scope = JSON.stringify([organizationId, history, enabled]);
  const [data, setData] = useState<WatchData>(() => ({
    scope,
    policies: [],
    items: [],
    error: "",
    loading: enabled,
  }));
  const generation = useRef(0);
  const load = useCallback(async () => {
    if (!enabled) return;
    const ticket = ++generation.current;
    try {
      const header = { "x-organization-id": organizationId };
      const [p, a] = await Promise.all([
        api(organizationId).GET("/api/v1/watch/policies", {
          params: { header },
        }),
        api(organizationId).GET("/api/v1/watch/attention", {
          params: { header, query: { include_closed: history } },
        }),
      ]);
      if (ticket !== generation.current) return;
      const policies = unwrap(p);
      const items = unwrap(a);
      if (!Array.isArray(policies) || !Array.isArray(items))
        throw new Error("关注记录返回格式不正确，请稍后刷新。");
      setData({ scope, policies, items, error: "", loading: false });
    } catch (error) {
      if (ticket === generation.current)
        setData({
          scope,
          policies: [],
          items: [],
          error: error instanceof Error ? error.message : "读取失败",
          loading: false,
        });
    }
  }, [organizationId, history, enabled, scope]);

  useEffect(() => {
    setData({ scope, policies: [], items: [], error: "", loading: enabled });
    void load();
    return () => {
      generation.current++;
    };
  }, [load, scope, enabled]);
  useVisibleRefresh(load, enabled);

  // Never expose the previous tenant/history/role while the next read is pending.
  const visible = enabled && data.scope === scope;
  return {
    policies: visible ? data.policies : [],
    items: visible ? data.items : [],
    error: visible ? data.error : "",
    loading: enabled && (!visible || data.loading),
    load,
  };
}
