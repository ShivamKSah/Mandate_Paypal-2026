import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, setCsrf } from "./api";
import { message, type Action } from "./domain";
async function loadDashboard() {
  const session = await api.session();
  setCsrf(session.csrf_token);
  const [products, mandates, proposals, payments, cases, ledger, verify] =
    await Promise.all([
      api.catalog(),
      api.mandates(),
      api.proposals(),
      api.payments(),
      api.cases(),
      api.ledger(),
      api.verifyLedger().catch(() => null),
    ]);
  return {
    session,
    products,
    mandates,
    proposals,
    payments,
    cases,
    ledger,
    verify,
  };
}
type DashboardState =
  | { kind: "loading" }
  | { kind: "locked" }
  | { kind: "error"; text: string }
  | { kind: "ready"; data: Awaited<ReturnType<typeof loadDashboard>> };
type Notice = { kind: "success" | "error" | "info"; text: string };
export function useDashboard(initialNotice: Notice | null) {
  const [state, setState] = useState<DashboardState>({ kind: "loading" });
  const [notice, setNotice] = useState<Notice | null>(initialNotice);
  const [working, setWorking] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [now, setNow] = useState(Date.now());
  const refreshRequest = useRef<Promise<void> | null>(null);
  const actionInFlight = useRef(false);
  const epoch = useRef(0);
  const refresh = useCallback((): Promise<void> => {
    if (refreshRequest.current) return refreshRequest.current;
    const currentEpoch = epoch.current;
    setRefreshing(true);
    const request = loadDashboard()
      .then((data) => {
        if (currentEpoch === epoch.current) setState({ kind: "ready", data });
      })
      .catch((error) => {
        if (currentEpoch !== epoch.current) return;
        if (error instanceof ApiError && error.status === 401) {
          setCsrf("");
          setState({ kind: "locked" });
        } else setState({ kind: "error", text: message(error) });
      })
      .finally(() => {
        refreshRequest.current = null;
        setRefreshing(false);
      });
    refreshRequest.current = request;
    return request;
  }, []);
  useEffect(() => {
    void refresh();
  }, [refresh]);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  const action: Action = async (run, success) => {
    if (actionInFlight.current || refreshRequest.current) return;
    actionInFlight.current = true;
    setWorking(true);
    setNotice(null);
    try {
      await run();
      setNotice({ kind: "success", text: success });
    } catch (error) {
      setNotice({ kind: "error", text: message(error) });
    } finally {
      // An error can follow a committed reservation or an unknown provider result.
      await refresh();
      actionInFlight.current = false;
      setWorking(false);
    }
  };
  async function logout() {
    if (actionInFlight.current || refreshRequest.current) return;
    actionInFlight.current = true;
    setWorking(true);
    try {
      await api.logout();
      epoch.current += 1;
      setCsrf("");
      setNotice(null);
      setState({ kind: "locked" });
    } catch (error) {
      setNotice({ kind: "error", text: message(error) });
    } finally {
      actionInFlight.current = false;
      setWorking(false);
    }
  }
  return {
    state,
    notice,
    setNotice,
    working: working || refreshing,
    action,
    refresh,
    logout,
    now,
  };
}
