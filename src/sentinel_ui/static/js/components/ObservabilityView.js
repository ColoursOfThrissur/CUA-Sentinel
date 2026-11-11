import { React, useState } from 'https://esm.sh/react@18.3.1';
import htm from 'https://esm.sh/htm@3.1.1';
import { Icon } from '../icons.js';

const html = htm.bind(React.createElement);

export function ObservabilityView({ telemetry, mistakes, skills, tools }) {
  const [activeSubTab, setActiveSubTab] = useState('mistakes'); // 'mistakes' | 'skills' | 'organs'

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
              <div className="card-subtitle">Windows 11 AppContainer · PSUtil Real-time Sensors · Monotonic Lease Fencing</div>
            </div>
          </div>
        </div>

        <div className="spatial-grid-3col">
          <div className="card-glass" style=${{ padding: '16px', background: 'rgba(255, 255, 255, 0.02)' }}>
            <div style=${{ fontSize: '12px', color: '#94a3b8', marginBottom: '6px' }}>Available Host RAM Floor</div>
            <div style=${{ fontSize: '24px', fontWeight: 700, color: '#38bdf8' }}>
              ${Math.round(telemetry?.system?.available_ram_mb || 0)} MB
            </div>
            <div style=${{ fontSize: '11px', color: '#64748b', marginTop: '4px' }}>
              Enforced Floor: ≥ ${telemetry?.ram_floor_mb || 2500} MB
            </div>
          </div>

          <div className="card-glass" style=${{ padding: '16px', background: 'rgba(255, 255, 255, 0.02)' }}>
            <div style=${{ fontSize: '12px', color: '#94a3b8', marginBottom: '6px' }}>Monotonic Lease Counter</div>
            <div style=${{ fontSize: '24px', fontWeight: 700, color: '#a855f7' }}>
              #${telemetry?.lease?.active_monotonic_lease ?? '--'}
            </div>
            <div style=${{ fontSize: '11px', color: '#64748b', marginTop: '4px' }}>
              AT-B-10 Fencing Active · Zombie Worker Protection
            </div>
          </div>

          <div className="card-glass" style=${{ padding: '16px', background: 'rgba(255, 255, 255, 0.02)' }}>
            <div style=${{ fontSize: '12px', color: '#94a3b8', marginBottom: '6px' }}>System CPU Utilization</div>
            <div style=${{ fontSize: '24px', fontWeight: 700, color: '#10b981' }}>
              ${telemetry?.system?.cpu_percent || 0}%
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
        </div>

        <!-- Tab 1: Mistakes Ledger -->
        ${activeSubTab === 'mistakes' && html`
          <div style=${{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            ${(!mistakes || mistakes.length === 0) && html`
              <div className="empty-state">
                <div className="empty-state-text">No episodic mistakes recorded. Execution is 100% clean.</div>
              </div>
            `}

            ${(mistakes || []).map((m, idx) => html`
              <div
                key=${idx}
                className="card-glass"
                style=${{ padding: '16px', background: 'rgba(255, 255, 255, 0.02)' }}
              >
                <div style=${{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '6px' }}>
                  <span style=${{ fontWeight: 600, color: '#f43f5e' }}>${m.mistake_type}</span>
                  <span style=${{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: '#64748b' }}>
                    ${m.timestamp || m.created_at || 'Recorded'}
                  </span>
                </div>

                <div style=${{ fontSize: '12.5px', color: '#cbd5e1', marginBottom: '8px' }}>
                  <strong>Root Cause:</strong> ${m.root_cause}
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
                  <strong>Lesson:</strong> ${m.lesson}
                </div>
              </div>
            `)}
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

            ${(skills || []).map((sk, idx) => html`
              <div
                key=${idx}
                className="card-glass"
                style=${{ padding: '16px', background: 'rgba(255, 255, 255, 0.02)' }}
              >
                <div style=${{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
                  <span style=${{ fontWeight: 600, color: '#38bdf8' }}>${sk.name || sk.slug}</span>
                  <span className="pill success">Distilled</span>
                </div>

                <div style=${{ fontSize: '12px', color: '#94a3b8', marginBottom: '10px' }}>
                  ${sk.description || 'Autonomous reusable tool distilled from successful execution history.'}
                </div>

                <div style=${{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: '#64748b' }}>
                  Trigger: ${sk.trigger || sk.slug}
                </div>
              </div>
            `)}
          </div>
        `}

        <!-- Tab 3: Organ Catalog -->
        ${activeSubTab === 'organs' && html`
          <div className="spatial-grid-2col">
            ${(tools || []).map((tool, idx) => html`
              <div
                key=${idx}
                className="card-glass"
                style=${{ padding: '14px', background: 'rgba(255, 255, 255, 0.02)' }}
              >
                <div style=${{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '6px' }}>
                  <span style=${{ fontFamily: 'var(--font-mono)', fontWeight: 600, color: '#a5f3fc' }}>
                    ${tool.name || tool}
                  </span>
                  <span className=${`pill ${tool.is_write ? 'failed' : 'success'}`} style=${{ fontSize: '10px' }}>
                    ${tool.is_write ? 'Write Organ (PDP Fenced)' : 'Read-Only Sensory'}
                  </span>
                </div>

                <div style=${{ fontSize: '11.5px', color: '#94a3b8' }}>
                  ${tool.description || 'Sensory/Motor execution tool registered in Sentinel Broker.'}
                </div>
              </div>
            `)}
          </div>
        `}
      </div>
    </div>
  `;
}
