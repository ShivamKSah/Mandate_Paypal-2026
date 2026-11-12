import { useState } from "react";
import { LockKeyhole } from "lucide-react";
import { api, setCsrf } from "./api";
import { message } from "./domain";
export function Login({ onLogin }: { onLogin: () => Promise<void> }) {
  const [accessKey, setAccessKey] = useState("");
  const [error, setError] = useState("");
  const [working, setWorking] = useState(false);
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (working) return;
    setWorking(true);
    setError("");
    try {
      const session = await api.login(accessKey);
      setCsrf(session.csrf_token);
      setAccessKey("");
      await onLogin();
    } catch (error) {
      setError(message(error));
    } finally {
      setWorking(false);
    }
  }
  return (
    <main className="loading-screen">
      <form
        className="panel login-panel"
        onSubmit={(event) => void submit(event)}
      >
        <div className="brand-mark">M</div>
        <h1>Open your workspace</h1>
        <p>Enter your access key to manage sandbox spending authority.</p>
        <label>
          Access key
          <input
            type="password"
            autoComplete="current-password"
            required
            maxLength={512}
            value={accessKey}
            onChange={(event) => setAccessKey(event.target.value)}
            autoFocus
          />
        </label>
        {error && (
          <p className="inline-alert" role="alert">
            {error}
          </p>
        )}
        <button className="button-dark" disabled={working || !accessKey}>
          <LockKeyhole size={16} />
          {working ? "Opening…" : "Open workspace"}
        </button>
      </form>
    </main>
  );
}
