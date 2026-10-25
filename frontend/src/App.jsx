import React, { useEffect, useState } from "react";

const FLASK = "http://localhost:5000";

export default function App() {
  const [summary, setSummary] = useState({ total: 0, byColor: [] });
  const [logs, setLogs] = useState([]);

  // Refresh the database logs every 2 seconds.
  useEffect(() => {
    const load = async () => {
      try {
        const s = await (await fetch("/api/summary")).json();
        const l = await (await fetch("/api/logs")).json();
        if (!s.error) setSummary(s);
        if (Array.isArray(l)) setLogs(l);
      } catch (e) {
        console.error(e);
      }
    };
    load();
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="page">
      <h1>Real-Time Vehicle Analytics</h1>

      <div className="layout">
        <section>
          <h2>Live inference stream</h2>
          <img className="video" src={`${FLASK}/video_feed`} alt="live stream" />
        </section>

        <div>
          <section>
            <h2>Total vehicles</h2>
            <div className="total">{summary.total}</div>
            <ul>
              {summary.byColor.map((c) => (
                <li key={c.color}>
                  {c.color}: <b>{c.n}</b>
                </li>
              ))}
            </ul>
          </section>

          <section>
            <h2>Latest logs</h2>
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Type</th>
                  <th>Color</th>
                  <th>Dir</th>
                  <th>Time</th>
                </tr>
              </thead>
              <tbody>
                {logs.map((e) => (
                  <tr key={e.id}>
                    <td>{e.vehicle_id}</td>
                    <td>{e.vehicle_type}</td>
                    <td>{e.color}</td>
                    <td>{e.direction}</td>
                    <td>{new Date(e.ts).toLocaleTimeString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </div>
      </div>
    </div>
  );
}
