import { useEffect, useState } from "react";

type Stats = Record<string, number>;

const apiBase = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export function App() {
  const [stats, setStats] = useState<Stats>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const response = await fetch(`${apiBase}/api/stats`);
        if (!response.ok) throw new Error(`API returned ${response.status}`);
        const data = (await response.json()) as Stats;
        if (active) setStats(data);
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

  return (
    <main>
      <header>
        <p className="eyebrow">DISTRIBUTED JOB ORCHESTRATOR</p>
        <h1>Execution control room</h1>
        <p className="lede">Persistent job state, retries, and worker delivery made visible.</p>
      </header>
      {error && <p className="error">{error}</p>}
      <section className="cards">
        {Object.entries(stats).map(([key, value]) => (
          <article className="card" key={key}>
            <span>{key.replaceAll("_", " ")}</span>
            <strong>{value}</strong>
          </article>
        ))}
      </section>
    </main>
  );
}

