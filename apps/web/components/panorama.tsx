import { Building2, ArrowUpRight } from "lucide-react";
import type { CSSProperties } from "react";
import { formatTime, type Dashboard } from "../lib/api";

export function Panorama({
  data,
  onDepartment,
  onSupport,
}: {
  data: Dashboard;
  onDepartment: (id: string) => void;
  onSupport: () => void;
}) {
  const covered = data.departments.filter(
    (d) => d.coverage === "recorded",
  ).length;
  const total = data.departments.length;
  return (
    <section className="panorama" aria-label="企业运行全景">
      <div className="panorama-summary">
        <div className="status-line">
          <span className="status-dot" />
          当前运行态势
        </div>
        <h2>
          {data.support_work ? (
            <>
              {data.support_work} 项工作
              <br />
              需要支持<span>。</span>
            </>
          ) : data.total_work ? (
            <>
              进展在这里
              <br />
              逐渐清晰<span>。</span>
            </>
          ) : (
            <>
              从第一项工作
              <br />
              看见企业全局<span>。</span>
            </>
          )}
        </h2>
        <p>
          {data.total_work
            ? `已记录 ${data.total_work} 项工作，覆盖 ${covered} / ${total} 个部门。${data.support_work ? "有成员提出支持需求，点击查看具体事实。" : "尚未接入的业务信息仍待补充。"}`
            : "建立部门、邀请成员，记录重要工作。还没有数据的地方，保留未知。"}
        </p>
        {data.support_work > 0 && (
          <button className="text-action" onClick={onSupport}>
            查看支持需求 <ArrowUpRight size={16} />
          </button>
        )}
        <div className="summary-numbers">
          <div>
            <strong>{data.member_count}</strong>
            <span>企业成员</span>
          </div>
          <div>
            <strong>{data.active_work}</strong>
            <span>进行与待开始</span>
          </div>
          <div>
            <strong>{data.support_work}</strong>
            <span>需要支持</span>
          </div>
        </div>
      </div>
      <div
        className={`orbit ${total > 6 ? "orbit-many" : ""}`}
        aria-label="部门全景"
      >
        <div className="orbit-ring ring-outer" />
        <div className="orbit-ring ring-inner" />
        <div className="orbit-core">
          <span>{data.organization.name}</span>
          <strong>
            {total} <small>个部门</small>
          </strong>
          <p>{covered} 个已有工作记录</p>
        </div>
        <div className="orbit-nodes">
          {data.departments.map((d, i) => {
            const angle = (i / total) * 2 * Math.PI - Math.PI / 2;
            const style =
              total <= 6
                ? ({
                    "--x": `${50 + 36 * Math.cos(angle)}%`,
                    "--y": `${50 + 37 * Math.sin(angle)}%`,
                  } as CSSProperties)
                : {};
            return (
              <button
                className="department-node"
                style={style}
                key={d.department.id}
                onClick={() => onDepartment(d.department.id)}
              >
                <span className="node-icon">
                  <Building2 size={17} />
                </span>
                <span>
                  <strong>{d.department.name}</strong>
                  <small>
                    {d.member_count} 人 ·{" "}
                    {d.coverage === "unknown"
                      ? "未知 / 无数据"
                      : `${d.work_count} 项工作`}
                  </small>
                </span>
                <span
                  className={`node-dot ${d.support_count ? "needs-support" : d.coverage === "unknown" ? "unknown" : "recorded"}`}
                  aria-label={
                    d.support_count
                      ? "需要支持"
                      : d.coverage === "unknown"
                        ? "无数据"
                        : "已有记录"
                  }
                />
              </button>
            );
          })}
        </div>
        {!total && <div className="orbit-empty">从建立第一个部门开始</div>}
      </div>
      <div className="panorama-caption">
        <span>仅包含 coRoof 中已记录的工作 · 外部数据尚未接入</span>
        <span>
          最近记录{" "}
          {formatTime(data.last_updated_at, data.organization.timezone)}
        </span>
      </div>
    </section>
  );
}
