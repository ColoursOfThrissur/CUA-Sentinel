import { useState, useEffect } from 'https://esm.sh/react@18.3.1';
import { html } from '../html.js';
import { Icon } from '../icons.js';
import { api } from '../api.js';

export function ObservabilityView({ telemetry, mistakes, skills, tools }) {
  const [activeSubTab, setActiveSubTab] = useState('mistakes'); // 'mistakes' | 'skills' | 'organs' | 'storage'
  const [storageStats, setStorageStats] = useState(null);
  const [isPruning, setIsPruning] = useState(false);
  const [pruneResult, setPruneResult] = useState(null);

  const ramAvailable = telemetry?.hardware?.available_ram_mb ?? telemetry?.system?.available_ram_mb ?? 0;
  const lease = telemetry?.counts?.highest_lease_token ?? telemetry?.lease?.active_monotonic_lease ?? '--';
  const cpuPercent = telemetry?.hardware?.cpu_percent ?? 0;
  const totalTasks = telemetry?.counts?.tasks ?? 0;
  const totalAttempts = telemetry?.counts?.attempts ?? 0;

  const fetchStorage = async () => {
    try {
      const stats = await api.getStorageStats();
      setStorageStats(stats);
    } catch (e) {
      console.error('Failed to load storage stats:', e);
    }
  };

  useEffect(() => {
    if (activeSubTab === 'storage' && !storageStats) {
      fetchStorage();
    }
  }, [activeSubTab]);

  const handlePrune = async () => {
    setIsPruning(true);
    setPruneResult(null);
    try {
      const res = await api.pruneStorage({
        max_task_age_days: 7,
        max_tasks_count: 500,
        prune_workspaces: true,
        deduplicate_mistakes: true,
        vacuum: true,
      });
      setPruneResult(res?.result || res);
      await fetchStorage();
    } catch (err) {
      alert(`Pruning failed: ${err.message || err}`);
    } finally {
      setIsPruning(false);
    }
  };

  return html`
    <div style=${{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      <!-- Hardware Telemetry Dials & Health Status -->
      <div className="card-glass">
        <div className="card-header">
          <div className="card-title-group">
            <div className="card-icon">
              <${Icon} name="cpu" size=${16} />
            </div>
            <div>
              <div className="card-title">Hardware Telemetry & Runtime Boundaries</div>
              <div className="card-subtitle">Windows 11 AppContainer · PSUtil Sensors · Monotonic Lease Fencing · AT-B-10 Fencing</div>
            </div>
          </div>
        </div>

        <div className="spatial-grid-3col">
          <div className="card-glass" style=${{ padding: '16px', background: 'rgba(255, 255, 255, 0.02)' }}>
            <div style=${{ fontSize: '12px', color: '#94a3b8', marginBottom: '6px' }}>Available Host RAM Floor</div>
            <div style=${{ fontSize: '24px', fontWeight: 700, color: '#38bdf8' }}>
              ${Math.round(ramAvailable)} MB
            </div>
            <div style=${{ fontSize: '11px', color: '#64748b', marginTop: '4px' }}>
              Enforced Floor: ≥ 2,500 MB
            </div>
          </div>

          <div className="card-glass" style=${{ padding: '16px', background: 'rgba(255, 255, 255, 0.02)' }}>
            <div style=${{ fontSize: '12px', color: '#94a3b8', marginBottom: '6px' }}>Monotonic Lease Counter</div>
            <div style=${{ fontSize: '24px', fontWeight: 700, color: '#a855f7' }}>
              #${lease}
            </div>
            <div style=${{ fontSize: '11px', color: '#64748b', marginTop: '4px' }}>
              Total Attempts: ${totalAttempts} across ${totalTasks} Tasks
            </div>
          </div>

          <div className="card-glass" style=${{ padding: '16px', background: 'rgba(255, 255, 255, 0.02)' }}>
            <div style=${{ fontSize: '12px', color: '#94a3b8', marginBottom: '6px' }}>System CPU Utilization</div>
            <div style=${{ fontSize: '24px', fontWeight: 700, color: '#10b981' }}>
              ${Math.round(cpuPercent)}%
            </div>
            <div style=${{ fontSize: '11px', color: '#64748b', marginTop: '4px' }}>
              Host Throttle Cap: ≤ 85.0%
            </div>
          </div>
        </div>
      </div>

      <!-- Observability Sub-Navigation -->
      <div className="card-glass">
        <div style=${{ display: 'flex', gap: '8px', borderBottom: '1px solid var(--border-glass)', paddingBottom: '14px', marginBottom: '18px' }}>
          <button
            className=${`nav-pill-btn ${activeSubTab === 'mistakes' ? 'active' : ''}`}
            onClick=${() => setActiveSubTab('mistakes')}
          >
            <${Icon} name="activity" size=${14} />
            <span>Episodic Mistakes (${(mistakes || []).length})</span>
          </button>

          <button
            className=${`nav-pill-btn ${activeSubTab === 'skills' ? 'active' : ''}`}
            onClick=${() => setActiveSubTab('skills')}
          >
            <${Icon} name="sparkles" size=${14} />
            <span>Skill Bank (${(skills || []).length})</span>
          </button>

          <button
            className=${`nav-pill-btn ${activeSubTab === 'organs' ? 'active' : ''}`}
            onClick=${() => setActiveSubTab('organs')}
          >
            <${Icon} name="shield" size=${14} />
            <span>Sensory & Motor Organs (${(tools || []).length})</span>
          </button>

          <button
            className=${`nav-pill-btn ${activeSubTab === 'storage' ? 'active' : ''}`}
            onClick=${() => setActiveSubTab('storage')}
          >
            <${Icon} name="database" size=${14} />
            <span>Storage & Retention ${storageStats ? `(${storageStats.database_size_mb} MB)` : ''}</span>
          </button>
        </div>

        <!-- Tab 1: Mistakes Ledger -->
        ${activeSubTab === 'mistakes' && html`
          <div style=${{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            ${(!mistakes || mistakes.length === 0) && html`
              <div className="empty-state">
                <div className="empty-state-text">No episodic mistakes recorded. Execution is 100% clean.</div>
              </div>
            `}

            ${(mistakes || []).map((m, idx) => {
              const category = m.error_category || m.mistake_type || 'Execution Error';
              const signature = m.error_signature || m.root_cause || 'Semantic verification failure';
              const lesson = m.lesson_learned || m.lesson || 'Preserve invariant';
              let formattedTime = 'Recorded';
              if (m.ts) {
                try { formattedTime = new Date(m.ts * 1000).toLocaleString(); } catch (e) {}
              } else if (m.created_at || m.timestamp) {
                formattedTime = m.created_at || m.timestamp;
              }

              return html`
                <div
                  key=${m.id || idx}
                  className="card-glass"
                  style=${{ padding: '16px', background: 'rgba(255, 255, 255, 0.02)' }}
                >
                  <div style=${{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '6px' }}>
                    <span style=${{ fontWeight: 600, color: '#f43f5e' }}>${category}</span>
                    <span style=${{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: '#64748b' }}>
                      ${formattedTime} ${m.task_id ? `· ${m.task_id}` : ''}
                    </span>
                  </div>

                  <div style=${{ fontSize: '12.5px', color: '#cbd5e1', marginBottom: '8px' }}>
                    <strong>Root Cause Signature:</strong> ${signature}
                  </div>

                  <div
                    style=${{
                      fontSize: '12px',
                      fontFamily: 'var(--font-mono)',
                      background: 'rgba(244, 63, 94, 0.1)',
                      border: '1px solid rgba(244, 63, 94, 0.25)',
                      padding: '8px 12px',
                      borderRadius: 'var(--radius-sm)',
                      color: '#fca5a5',
                    }}
                  >
                    <strong>Imperative Lesson:</strong> ${lesson}
                  </div>
                </div>
              `;
            })}
          </div>
        `}

        <!-- Tab 2: Skill Bank -->
        ${activeSubTab === 'skills' && html`
          <div className="spatial-grid-2col">
            ${(!skills || skills.length === 0) && html`
              <div className="empty-state">
                <div className="empty-state-text">No distilled skills stored in the dynamic skill bank yet.</div>
              </div>
            `}

            ${(skills || []).map((sk, idx) => {
              const skillName = sk.name || sk.id || sk.slug;
              const skillDesc = sk.description || 'Autonomous reusable tool distilled from successful execution history.';
              return html`
                <div
                  key=${sk.id || idx}
                  className="card-glass"
                  style=${{ padding: '16px', background: 'rgba(255, 255, 255, 0.02)' }}
                >
                  <div style=${{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
                    <span style=${{ fontWeight: 600, color: '#38bdf8' }}>${skillName}</span>
                    <span className="pill success">Distilled</span>
                  </div>

                  <div style=${{ fontSize: '12px', color: '#94a3b8', marginBottom: '10px' }}>
                    ${skillDesc}
                  </div>

                  <div style=${{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: '#64748b' }}>
                    ID: ${sk.id || skillName} ${sk.version ? `· v${sk.version}` : ''}
                  </div>
                </div>
              `;
            })}
          </div>
        `}

        <!-- Tab 3: Organ Catalog -->
        ${activeSubTab === 'organs' && html`
          <div className="spatial-grid-2col">
            ${(tools || []).map((tool, idx) => {
              const toolName = tool.name || tool;
              const effectClass = tool.effect_class || 'none';
              const isWrite = effectClass !== 'none';
              return html`
                <div
                  key=${idx}
                  className="card-glass"
                  style=${{ padding: '14px', background: 'rgba(255, 255, 255, 0.02)' }}
                >
                  <div style=${{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '6px' }}>
                    <span style=${{ fontFamily: 'var(--font-mono)', fontWeight: 600, color: '#a5f3fc' }}>
                      ${toolName}
                    </span>
                    <span className=${`pill ${isWrite ? 'verifying' : 'success'}`} style=${{ fontSize: '10px' }}>
                      ${isWrite ? `Motor (${effectClass})` : 'Sensory (Read-Only)'}
                    </span>
                  </div>

                  <div style=${{ fontSize: '11.5px', color: '#94a3b8' }}>
                    ${tool.description || 'Sensory/Motor execution tool registered in Sentinel Broker.'}
                  </div>
                </div>
              `;
            })}
          </div>
        `}
        <!-- Tab 4: Storage & Data Retention -->
        ${activeSubTab === 'storage' && html`
          <div style=${{ display: 'flex', flexDirection: 'column', gap: '18px' }}>
            <div style=${{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
              <div>
                <div style=${{ fontWeight: 600, color: '#f8fafc', fontSize: '15px' }}>Storage Footprint & Autonomous Retention</div>
                <div style=${{ fontSize: '12px', color: '#94a3b8', marginTop: '2px' }}>
                  Enforce SQLite table TTLs, mistake deduplication, and workspace artifact lifecycle hygiene.
                </div>
              </div>

              <div style=${{ display: 'flex', gap: '8px' }}>
                <button
                  className="btn-glass"
                  onClick=${fetchStorage}
                  disabled=${isPruning}
                  style=${{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', padding: '6px 14px' }}
                >
                  <${Icon} name="refresh-cw" size=${13} />
                  <span>Refresh Stats</span>
                </button>

                <button
                  className="btn-accent"
                  onClick=${handlePrune}
                  disabled=${isPruning}
                  style=${{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', padding: '6px 14px' }}
                >
                  <${Icon} name="trash" size=${13} />
                  <span>${isPruning ? 'Pruning Storage...' : 'Prune Stale Data Now'}</span>
                </button>
              </div>
            </div>

            ${pruneResult && html`
              <div
                style=${{
                  background: 'rgba(16, 185, 129, 0.1)',
                  border: '1px solid rgba(16, 185, 129, 0.3)',
                  borderRadius: 'var(--radius-sm)',
                  padding: '12px 16px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '6px',
                }}
              >
                <div style=${{ display: 'flex', alignItems: 'center', gap: '8px', color: '#34d399', fontWeight: 600, fontSize: '13px' }}>
                  <${Icon} name="check-circle" size=${15} />
                  <span>Pruning Complete · Reclaimed Space & Cleaned Ledgers</span>
                </div>
                <div style=${{ fontSize: '12px', color: '#cbd5e1', display: 'flex', gap: '16px', flexWrap: 'wrap' }}>
                  <span>Tasks Pruned: <strong>${pruneResult.tasks_pruned}</strong></span>
                  <span>Duplicate Mistakes: <strong>${pruneResult.mistakes_pruned}</strong></span>
                  <span>DAG Runs: <strong>${pruneResult.dag_runs_pruned}</strong></span>
                  <span>Workspace Files: <strong>${pruneResult.workspace_files_removed}</strong></span>
                  <span>DB Space Reclaimed: <strong>${Math.round(pruneResult.db_bytes_reclaimed / 1024)} KB</strong></span>
                  <span>VACUUM: <strong>${pruneResult.vacuumed ? 'Compacted' : 'Skipped'}</strong></span>
                </div>
              </div>
            `}

            <div className="spatial-grid-2col">
              <div className="card-glass" style=${{ padding: '16px', background: 'rgba(255, 255, 255, 0.02)' }}>
                <div style=${{ fontSize: '12px', color: '#94a3b8', marginBottom: '8px', fontWeight: 600 }}>
                  SQLite Core Database (`sentinel_core.db`)
                </div>
                <div style=${{ fontSize: '26px', fontWeight: 700, color: '#38bdf8', marginBottom: '12px' }}>
                  ${storageStats ? `${storageStats.database_size_mb} MB` : 'Loading...'}
                </div>
                <div style=${{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '11.5px', color: '#cbd5e1' }}>
                  ${storageStats?.table_counts && Object.entries(storageStats.table_counts).map(([tbl, cnt]) => html`
                    <div key=${tbl} style=${{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid rgba(255,255,255,0.04)', paddingBottom: '3px' }}>
                      <span style=${{ fontFamily: 'var(--font-mono)', color: '#94a3b8' }}>${tbl}</span>
                      <span style=${{ fontWeight: 600 }}>${cnt} rows</span>
                    </div>
                  `)}
                </div>
              </div>

              <div className="card-glass" style=${{ padding: '16px', background: 'rgba(255, 255, 255, 0.02)' }}>
                <div style=${{ fontSize: '12px', color: '#94a3b8', marginBottom: '8px', fontWeight: 600 }}>
                  Workspace Artifacts & Inspection Rigs
                </div>
                <div style=${{ fontSize: '26px', fontWeight: 700, color: '#a855f7', marginBottom: '12px' }}>
                  ${storageStats ? `${storageStats.workspace_size_mb} MB` : 'Loading...'}
                </div>
                <div style=${{ fontSize: '12px', color: '#94a3b8', marginBottom: '16px' }}>
                  Total Stored Artifacts: <strong>${storageStats?.workspace_file_count ?? 0} files</strong>
                </div>

                <div style=${{ background: 'rgba(0,0,0,0.2)', padding: '12px', borderRadius: 'var(--radius-sm)', fontSize: '11.5px', color: '#94a3b8' }}>
                  <div style=${{ fontWeight: 600, color: '#e2e8f0', marginBottom: '4px' }}>Active Retention Policies:</div>
                  <div>• Terminal Tasks TTL: <strong>7 days</strong></div>
                  <div>• Max Terminal Task Capacity: <strong>500 tasks</strong></div>
                  <div>• Ephemeral Mistakes: <strong>Deduplicated to latest signature</strong></div>
                  <div>• Orphan Workspace Meshes: <strong>Auto-pruned</strong></div>
                  <div>• Database Maintenance: <strong>VACUUM & PRAGMA optimize</strong></div>
                </div>
              </div>
            </div>
          </div>
        `}
      </div>
    </div>
  `;
}
