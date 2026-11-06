import { ArrowUpRight, Clock3, Network, Pause, Play } from "lucide-react";
import { useState, type CSSProperties } from "react";
import { formatTime, type Dashboard } from "../lib/api";
import { departmentStatus, StatusIcon, StatusLabel } from "./status";
import "./living-panorama.css";

export function Panorama({
  data,
  onDepartment,
  onSupport,
}: {
  data: Dashboard;
  onDepartment: (id: string) => void;
  onSupport: () => void;
}) {
  const [pointedId, setPointedId] = useState<string | null>(null);
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const [motionPaused, setMotionPaused] = useState(false);
  const preview =
    data.departments.find((d) => d.department.id === focusedId) ||
    data.departments.find((d) => d.department.id === pointedId);
  const covered = data.departments.filter(
    (d) => d.coverage === "recorded",
  ).length;
  const total = data.departments.length;
  return (
    <section
      className="panorama living-panorama"
      aria-label="企业运行全景"
      data-motion-paused={motionPaused}
    >
      <div className="panorama-summary">
        <div className="status-line">
          <StatusLabel
            status={
              data.support_work > 0
                ? "support"
                : data.total_work > 0
                  ? "recorded"
                  : "unknown"
            }
            variant="inline"
          >
            {data.support_work > 0
              ? "有人需要帮助"
              : data.total_work > 0
                ? "已记录的企业情况"
                : "等待工作记录"}
          </StatusLabel>
        </div>
        <h2>
          {data.support_work ? (
            <>{data.support_work} 项工作需要支持</>
          ) : data.total_work ? (
            <>{data.active_work} 项工作待完成</>
          ) : (
            <>从第一项工作开始</>
          )}
        </h2>
        <p>
          {data.total_work
            ? `${covered} / ${total} 个部门有工作记录；未记录的情况仍未知。`
            : "记录工作后，这里会呈现各部门的真实进展。"}
        </p>
        {data.support_work > 0 && (
          <button className="text-action support-action" onClick={onSupport}>
            查看支持需求 <ArrowUpRight size={16} />
          </button>
        )}
        <div className="summary-numbers">
          <div>
            <strong className="panorama-value" key={data.member_count}>
              {data.member_count}
            </strong>
            <span>企业成员</span>
          </div>
          <div>
            <strong className="panorama-value" key={data.active_work}>
              {data.active_work}
            </strong>
            <span>进行与待开始</span>
          </div>
          <div
            className="support-metric"
            data-status={data.support_work > 0 ? "support" : "planned"}
          >
            <strong className="panorama-value" key={data.support_work}>
              {data.support_work}
              {data.support_work > 0 && (
                <StatusIcon status="support" size={17} />
              )}
            </strong>
            <span>需要支持</span>
          </div>
        </div>
      </div>
      <div
        // A changed department set restarts every orbit at the same phase;
        // normal record refreshes preserve their animation timelines.
        key={data.departments.map((d) => d.department.id).join("|")}
        className={`orbit ${total > 6 ? "orbit-many" : total ? "orbit-moving" : ""}`}
        aria-label="部门全景"
        onMouseLeave={() => setPointedId(null)}
      >
        <div className="orbit-ring ring-outer" aria-hidden="true" />
        <div className="orbit-ring ring-inner" aria-hidden="true" />
        {total > 0 && total <= 6 && (
          <svg
            className="panorama-connections"
            viewBox="0 0 2 2"
            preserveAspectRatio="none"
            aria-hidden="true"
          >
            <g className="panorama-spokes">
              {data.departments.map((d, i) => {
                const angle = (i / total) * 2 * Math.PI - Math.PI / 2;
                return (
                  <line
                    key={d.department.id}
                    x1="1"
                    y1="1"
                    x2={1 + Math.cos(angle)}
                    y2={1 + Math.sin(angle)}
                    vectorEffect="non-scaling-stroke"
                    data-highlighted={
                      preview?.department.id === d.department.id
                    }
                  />
                );
              })}
            </g>
          </svg>
        )}
        <div
          className="orbit-core"
          data-preview={!!preview}
          role="region"
          aria-label={preview ? "部门预览" : "组织记录概览"}
        >
          <div
            className="panorama-core-content"
            key={preview?.department.id || data.organization.id}
          >
            <span className="panorama-core-symbol" aria-hidden="true">
              {preview ? (
                <StatusIcon status={departmentStatus(preview)} size={19} />
              ) : (
                <Network size={19} />
              )}
            </span>
            <span
              className="panorama-core-name"
              title={preview?.department.name || data.organization.name}
            >
              {preview?.department.name || data.organization.name}
            </span>
            <strong>
              {preview ? preview.work_count : total}{" "}
              <small>{preview ? "项工作" : "个部门"}</small>
            </strong>
            <p>
              {preview
                ? preview.coverage === "unknown"
                  ? "暂无记录 · 状态未知"
                  : `${preview.active_count} 项进行与待开始`
                : `${covered} 个已有工作记录`}
            </p>
            <span className="panorama-core-hint">
              {preview ? "点击部门，查看具体工作" : "指向部门，预览工作记录"}
            </span>
          </div>
        </div>
        <div className="orbit-nodes">
          {data.departments.map((d, i) => {
            const angle = (i / total) * 2 * Math.PI - Math.PI / 2;
            const style =
              total <= 6
                ? ({
                    "--x": `${50 + 36 * Math.cos(angle)}%`,
                    "--y": `${50 + 37 * Math.sin(angle)}%`,
                    "--node-order": Math.min(i, 5),
                    "--orbit-angle": `${(i / total) * 360 - 90}deg`,
                  } as CSSProperties)
                : ({ "--node-order": Math.min(i, 5) } as CSSProperties);
            return (
              <button
                className="department-node"
                data-status={departmentStatus(d)}
                data-highlighted={preview?.department.id === d.department.id}
                style={style}
                key={d.department.id}
                onMouseEnter={() => setPointedId(d.department.id)}
                onFocus={() => setFocusedId(d.department.id)}
                onBlur={() => setFocusedId(null)}
                onClick={() => onDepartment(d.department.id)}
              >
                <span className="node-icon">
                  <StatusIcon status={departmentStatus(d)} size={17} />
                </span>
                <span>
                  <strong>{d.department.name}</strong>
                  <small>
                    {d.member_count} 人 ·{" "}
                    {d.support_count > 0
                      ? `${d.support_count} 项需要支持`
                      : d.coverage === "unknown"
                        ? "未知 / 无数据"
                        : `${d.work_count} 项工作`}
                  </small>
                  <span className="node-record" key={d.updated_at || "unknown"}>
                    <Clock3 size={10} aria-hidden="true" />
                    {d.updated_at
                      ? formatTime(d.updated_at, data.organization.timezone)
                      : "等待第一条记录"}
                  </span>
                </span>
                <ArrowUpRight
                  className="node-open"
                  size={14}
                  aria-hidden="true"
                />
              </button>
            );
          })}
        </div>
        {!total && <div className="orbit-empty">从建立第一个部门开始</div>}
      </div>
      <div className="panorama-caption">
        <span>仅包含当前获授权的已记录工作 · 未覆盖的信息仍然未知</span>
        {total > 0 && total <= 6 && (
          <button
            className="orbit-motion-toggle"
            aria-label={motionPaused ? "继续全景动画" : "暂停全景动画"}
            aria-pressed={motionPaused}
            onClick={() => setMotionPaused((paused) => !paused)}
          >
            {motionPaused ? <Play size={12} /> : <Pause size={12} />}
            {motionPaused ? "继续转动" : "暂停转动"}
          </button>
        )}
        <span>
          最近记录{" "}
          {formatTime(data.last_updated_at, data.organization.timezone)}
        </span>
      </div>
    </section>
  );
}
