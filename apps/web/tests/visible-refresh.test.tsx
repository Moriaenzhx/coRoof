import { act, render } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useVisibleRefresh } from "../lib/use-visible-refresh";
function Probe({
  refresh,
  enabled = true,
}: {
  refresh: () => Promise<unknown>;
  enabled?: boolean;
}) {
  useVisibleRefresh(refresh, enabled);
  return null;
}
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});
it("refreshes visible work, skips hidden tabs and stops on unmount", async () => {
  vi.useFakeTimers();
  const refresh = vi.fn().mockResolvedValue(undefined);
  const hidden = vi
    .spyOn(document, "visibilityState", "get")
    .mockReturnValue("visible");
  const view = render(<Probe refresh={refresh} />);
  await act(() => vi.advanceTimersByTimeAsync(30000));
  expect(refresh).toHaveBeenCalledTimes(1);
  hidden.mockReturnValue("hidden");
  await act(() => vi.advanceTimersByTimeAsync(30000));
  expect(refresh).toHaveBeenCalledTimes(1);
  hidden.mockReturnValue("visible");
  await act(async () => {
    document.dispatchEvent(new Event("visibilitychange"));
  });
  expect(refresh).toHaveBeenCalledTimes(2);
  view.unmount();
  await act(() => vi.advanceTimersByTimeAsync(30000));
  expect(refresh).toHaveBeenCalledTimes(2);
});
it("does not overlap slow requests or poll while editing", async () => {
  vi.useFakeTimers();
  const refresh = vi.fn(() => new Promise<void>(() => {}));
  const view = render(<Probe refresh={refresh} />);
  await act(() => vi.advanceTimersByTimeAsync(90000));
  expect(refresh).toHaveBeenCalledTimes(1);
  view.rerender(<Probe refresh={refresh} enabled={false} />);
  await act(() => vi.advanceTimersByTimeAsync(90000));
  expect(refresh).toHaveBeenCalledTimes(1);
});
