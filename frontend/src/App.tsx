import { FormEvent, useEffect, useMemo, useState } from "react";

type Stats = Record<string, number>;
type Job = {
  id: string;
  type: string;
  payload: Record<string, unknown>;
  status: string;
  progress: number;
  result: Record<string, unknown> | null;
  error_message: string | null;
  attempt_count: number;
  max_attempts: number;
  created_at: string;
  updated_at: string;
};
type JobEvent = { id: string; event_type: string; message: string; timestamp: string };

const apiBase = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export function App() {
  const [stats, setStats] = useState<Stats>({});
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selected, setSelected] = useState<Job | null>(null);
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [type, setType] = useState("delayed_sum");
  const [payload, setPayload] = useState('{"numbers":[1,2,3,4],"delay_ms":200}');
  const [idempotencyKey, setIdempotencyKey] = useState<string>(crypto.randomUUID());
  const [error, setError] = useState<string | null>(null);

  const loadJobs = async () => {
    const response = await fetch(`${apiBase}/api/jobs?limit=50`);
    if (!response.ok) throw new Error(`Jobs API returned ${response.status}`);
    setJobs((await response.json()) as Job[]);
  };

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const response = await fetch(`${apiBase}/api/stats`);
        if (!response.ok) throw new Error(`API returned ${response.status}`);
        const data = (await response.json()) as Stats;
        if (active) setStats(data);
        await loadJobs();
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : "Unable to load stats");
      }
    };
    void load();
    const timer = window.setInterval(load, 2000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    if (!selected) return;
    const loadEvents = async () => {
      const response = await fetch(`${apiBase}/api/jobs/${selected.id}/events`);
      if (response.ok) setEvents((await response.json()) as JobEvent[]);
    };
    void loadEvents();
    const websocket = new WebSocket(`${apiBase.replace("http", "ws")}/ws/jobs/${selected.id}`);
    websocket.onmessage = (message) => {
      const update = JSON.parse(message.data) as { job: Job };
      setSelected(update.job);
      setJobs((current) => current.map((job) => (job.id === update.job.id ? update.job : job)));
    };
    return () => websocket.close();
  }, [selected?.id]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    try {
      const response = await fetch(`${apiBase}/api/jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ type, payload: JSON.parse(payload), idempotency_key: idempotencyKey }),
      });
      if (!response.ok) throw new Error(await response.text());
      const job = (await response.json()) as Job;
      setSelected(job);
      await loadJobs();
      setIdempotencyKey(crypto.randomUUID());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to create job");
    }
  };

  const statusCards = useMemo(() => Object.entries(stats).filter(([key]) => key !== "total"), [stats]);

  return (
    <main>
      <header>
        <p className="eyebrow">DISTRIBUTED JOB ORCHESTRATOR</p>
        <h1>Execution control room</h1>
        <p className="lede">Persistent job state, retries, and worker delivery made visible.</p>
      </header>
      {error && <p className="error">{error}</p>}
      <section className="cards">
        {statusCards.map(([key, value]) => (
          <article className="card" key={key}>
            <span>{key.replaceAll("_", " ")}</span>
            <strong>{value}</strong>
          </article>
        ))}
      </section>
      <section className="workspace">
        <form className="panel" onSubmit={submit}>
          <h2>Create job</h2>
          <label>Handler<select value={type} onChange={(event) => {
            const next = event.target.value;
            setType(next);
            setPayload(next === "batch_transform" ? '{"items":["alpha","beta"]}' : next === "unstable_demo" ? '{"fail_until_attempt":2}' : '{"numbers":[1,2,3,4],"delay_ms":200}');
          }}><option value="delayed_sum">delayed_sum</option><option value="batch_transform">batch_transform</option><option value="unstable_demo">unstable_demo</option></select></label>
          <label>Idempotency key<input value={idempotencyKey} onChange={(event) => setIdempotencyKey(event.target.value)} maxLength={128} /></label>
          <label>Payload<textarea value={payload} onChange={(event) => setPayload(event.target.value)} rows={5} /></label>
          <button type="submit">Queue job</button>
        </form>
        <section className="panel jobs-panel"><h2>Recent jobs</h2>{jobs.length === 0 ? <p className="muted">No jobs yet.</p> : jobs.map((job) => <button className={`job-row ${selected?.id === job.id ? "selected" : ""}`} key={job.id} onClick={() => setSelected(job)}><span>{job.type}<small>{job.id.slice(0, 8)}</small></span><span>{job.status}<progress max="100" value={job.progress} /></span></button>)}</section>
        <section className="panel detail"><h2>Job detail</h2>{selected ? <><p className="detail-id">{selected.id}</p><p><b>{selected.status}</b> · attempt {selected.attempt_count}/{selected.max_attempts}</p><progress max="100" value={selected.progress} /><pre>{JSON.stringify(selected.result ?? selected.error_message ?? selected.payload, null, 2)}</pre><h3>Timeline</h3>{events.map((item) => <p className="event" key={item.id}><b>{item.event_type}</b><br />{item.message}<small>{new Date(item.timestamp).toLocaleString()}</small></p>)}</> : <p className="muted">Select a job to inspect its persisted timeline.</p>}</section>
      </section>
    </main>
  );
}

