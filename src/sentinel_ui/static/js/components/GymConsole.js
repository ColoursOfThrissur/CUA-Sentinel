import { useState, useEffect } from 'https://esm.sh/react@18.3.1';
import { html } from '../html.js';
import { Icon } from '../icons.js';
import { api } from '../api.js';

export function GymConsole({ onOpenViewport, liveBlueprintStage }) {
  const [gymStatus, setGymStatus] = useState(null);
  const [loading, setLoading] = useState(false);
  const [hours, setHours] = useState(5.0);
  const [selectedSnapshot, setSelectedSnapshot] = useState(null);

  const fetchStatus = async () => {
    try {
      const data = await api.getGymStatus();
      setGymStatus(data);
    } catch (e) {
      console.debug('Failed to fetch gym status', e);
    }
  };

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 2500);
    return () => clearInterval(interval);
  }, []);

  const handleStart = async () => {
    setLoading(true);
    try {
      await api.startGym({ max_hours: parseFloat(hours) || 5.0, domain: '3d' });
      await fetchStatus();
    } catch (e) {
      alert('Failed to start Gymnasium: ' + e.message);
    } finally {
      setLoading(false);
    }
  };

  const handleStop = async () => {
    setLoading(true);
    try {
      await api.stopGym();
      await fetchStatus();
    } catch (e) {
      alert('Failed to stop Gymnasium: ' + e.message);
    } finally {
      setLoading(false);
    }
  };

  const formatSecs = (sec) => {
    if (!sec || sec <= 0) return '00h 00m';
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    return `${String(h).padStart(2, '0')}h ${String(m).padStart(2, '0')}m`;
  };

  const isRunning = gymStatus?.is_running;
  const recentCycles = gymStatus?.recent_cycles || [];
  const latestCycle = recentCycles.length > 0 ? recentCycles[recentCycles.length - 1] : null;

  return html`
    <div style=${{ padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1.25rem', height: '100%', overflowY: 'auto' }}>
      
      <!-- Header & Top Control Bar -->
      <div style=${{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '1.25rem 1.5rem',
        background: 'var(--bg-surface, #1e293b)',
        border: '1px solid var(--border-subtle, rgba(255,255,255,0.08))',
        borderRadius: '10px',
      }}>
        <div style=${{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
          <div style=${{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <span style=${{ fontSize: '1.2rem', fontWeight: 'bold', letterSpacing: '0.05em' }}>
              AUTONOMOUS GYMNASIUM & SELF-EVOLUTION
            </span>
            <span style=${{
              padding: '0.2rem 0.6rem',
              borderRadius: '999px',
              fontSize: '0.75rem',
              fontWeight: 600,
              background: isRunning ? 'rgba(16, 185, 129, 0.2)' : 'rgba(148, 163, 184, 0.15)',
              color: isRunning ? 'var(--accent-success, #10b981)' : '#94a3b8',
              border: `1px solid ${isRunning ? 'var(--accent-success, #10b981)' : '#64748b'}`,
              display: 'flex',
              alignItems: 'center',
              gap: '0.35rem',
            }}>
              <span style=${{
                width: '6px',
                height: '6px',
                borderRadius: '50%',
                background: isRunning ? '#10b981' : '#94a3b8',
              }}></span>
              ${isRunning ? 'ACTIVE (Self-Play Training)' : 'IDLE'}
            </span>
          </div>
          <span style=${{ fontSize: '0.8rem', opacity: 0.7 }}>
            Closed-loop physical self-play: generates frontier challenges, renders 4-angle visual snapshots in Blender, enforces harsh sensory scoring, and distills verified skills.
          </span>
        </div>

        <!-- Controls -->
        <div style=${{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          ${!isRunning && html`
            <div style=${{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.85rem' }}>
              <span style=${{ opacity: 0.8 }}>Max Run:</span>
              <input
                type="number"
                min="0.1"
                max="24"
                step="0.5"
                value=${hours}
                onChange=${(e) => setHours(e.target.value)}
                style=${{
                  width: '60px',
                  padding: '0.3rem 0.5rem',
                  background: 'rgba(0,0,0,0.3)',
                  border: '1px solid var(--border-subtle, rgba(255,255,255,0.15))',
                  borderRadius: '4px',
                  color: '#fff',
                  textAlign: 'center',
                }}
              />
              <span style=${{ opacity: 0.8 }}>hours</span>
            </div>
          `}

          ${isRunning ? html`
            <button
              onClick=${handleStop}
              disabled=${loading}
              style=${{
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem',
                padding: '0.6rem 1.2rem',
                background: 'rgba(239, 68, 68, 0.2)',
                color: 'var(--accent-danger, #ef4444)',
                border: '1px solid var(--accent-danger, #ef4444)',
                borderRadius: '6px',
                fontWeight: 'bold',
                cursor: 'pointer',
              }}
            >
              <${Icon} name="x" size=${16} />
              Stop Self-Evolution
            </button>
          ` : html`
            <button
              onClick=${handleStart}
              disabled=${loading}
              style=${{
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem',
                padding: '0.6rem 1.25rem',
                background: 'var(--accent-primary, #3b82f6)',
                color: '#fff',
                border: 'none',
                borderRadius: '6px',
                fontWeight: 'bold',
                cursor: 'pointer',
              }}
            >
              <${Icon} name="zap" size=${16} />
              Start 5-Hour Self-Evolution
            </button>
          `}
        </div>
      </div>

      <!-- Stats Grid -->
      <div style=${{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
        gap: '1rem',
      }}>
        <div style=${{ padding: '1rem', background: 'var(--bg-surface, #1e293b)', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.06)' }}>
          <div style=${{ fontSize: '0.75rem', opacity: 0.6, textTransform: 'uppercase', marginBottom: '0.4rem' }}>Loop Duration</div>
          <div style=${{ fontSize: '1.4rem', fontWeight: 'bold' }}>
            ${formatSecs(gymStatus?.elapsed_seconds)}
            <span style=${{ fontSize: '0.85rem', opacity: 0.5, marginLeft: '0.5rem' }}>
              / ${formatSecs(gymStatus?.remaining_seconds ? gymStatus.elapsed_seconds + gymStatus.remaining_seconds : 18000)}
            </span>
          </div>
        </div>

        <div style=${{ padding: '1rem', background: 'var(--bg-surface, #1e293b)', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.06)' }}>
          <div style=${{ fontSize: '0.75rem', opacity: 0.6, textTransform: 'uppercase', marginBottom: '0.4rem' }}>Completed Cycles</div>
          <div style=${{ fontSize: '1.4rem', fontWeight: 'bold' }}>
            ${gymStatus?.total_cycles_completed ?? 0}
          </div>
        </div>

        <div style=${{ padding: '1rem', background: 'var(--bg-surface, #1e293b)', borderRadius: '8px', border: '1px solid rgba(16, 185, 129, 0.3)' }}>
          <div style=${{ fontSize: '0.75rem', color: '#10b981', textTransform: 'uppercase', marginBottom: '0.4rem' }}>Skills Evolved (Score >= 0.82)</div>
          <div style=${{ fontSize: '1.4rem', fontWeight: 'bold', color: '#10b981' }}>
            +${gymStatus?.skills_evolved_count ?? 0}
          </div>
        </div>

        <div style=${{ padding: '1rem', background: 'var(--bg-surface, #1e293b)', borderRadius: '8px', border: '1px solid rgba(245, 158, 11, 0.3)' }}>
          <div style=${{ fontSize: '0.75rem', color: '#f59e0b', textTransform: 'uppercase', marginBottom: '0.4rem' }}>Anti-Patterns Prevented</div>
          <div style=${{ fontSize: '1.4rem', fontWeight: 'bold', color: '#f59e0b' }}>
            ${gymStatus?.anti_patterns_recorded_count ?? 0}
          </div>
        </div>

        <div style=${{ padding: '1rem', background: 'var(--bg-surface, #1e293b)', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.06)' }}>
          <div style=${{ fontSize: '0.75rem', opacity: 0.6, textTransform: 'uppercase', marginBottom: '0.4rem' }}>Empirical Average Score</div>
          <div style=${{ fontSize: '1.4rem', fontWeight: 'bold' }}>
            ${(gymStatus?.average_score ?? 0).toFixed(2)} <span style=${{ fontSize: '0.85rem', opacity: 0.5 }}>/ 1.00</span>
          </div>
        </div>
      </div>

      <!-- Live Progressive LoD Blueprint Stepper -->
      ${liveBlueprintStage && html`
        <div style=${{
          padding: '1.25rem',
          background: 'rgba(56, 189, 248, 0.08)',
          border: '1px solid rgba(56, 189, 248, 0.3)',
          borderRadius: '8px',
          display: 'flex',
          flexDirection: 'column',
          gap: '0.75rem',
        }}>
          <div style=${{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style=${{ fontSize: '0.85rem', fontWeight: 600, color: '#38bdf8' }}>
              🔬 PROGRESSIVE LoD PIPELINE: STAGE ${liveBlueprintStage.stage} (${liveBlueprintStage.stage_name})
            </span>
            <span style=${{
              padding: '0.15rem 0.5rem',
              borderRadius: '999px',
              fontSize: '0.7rem',
              fontWeight: 600,
              background: liveBlueprintStage.status === 'running' ? 'rgba(56, 189, 248, 0.2)' : 'rgba(16, 185, 129, 0.2)',
              color: liveBlueprintStage.status === 'running' ? '#38bdf8' : '#10b981',
              border: `1px solid ${liveBlueprintStage.status === 'running' ? '#38bdf8' : '#10b981'}`,
            }}>
              ${liveBlueprintStage.status === 'running' ? 'EXECUTING' : 'COMPLETED'}
            </span>
          </div>

          <div style=${{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: '0.5rem' }}>
            ${[
              { num: 1.0, title: 'Anatomy', desc: 'Hardware Discovery' },
              { num: 2.0, title: 'Kinematics', desc: 'Parent-Child Tree' },
              { num: 3.0, title: 'Dimensions', desc: 'Metric Offsets' },
              { num: 3.5, title: 'Viability', desc: 'ReAct CAD Audit' },
              { num: 4.0, title: 'Materials', desc: 'PBR Shaders' },
            ].map((stg) => {
              const currentNum = parseFloat(liveBlueprintStage.stage) || 0;
              const isPast = currentNum > stg.num;
              const isCurrent = Math.abs(currentNum - stg.num) < 0.3;
              return html`
                <div
                  key=${stg.num}
                  style=${{
                    background: isCurrent ? 'rgba(56, 189, 248, 0.2)' : isPast ? 'rgba(16, 185, 129, 0.1)' : 'rgba(255, 255, 255, 0.02)',
                    border: `1px solid ${isCurrent ? '#38bdf8' : isPast ? '#10b981' : 'rgba(255, 255, 255, 0.08)'}`,
                    borderRadius: '6px',
                    padding: '0.5rem',
                  }}
                >
                  <div style=${{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', fontWeight: 600, color: isCurrent ? '#38bdf8' : isPast ? '#34d399' : '#94a3b8' }}>
                    <span>${stg.title}</span>
                    <span>S${stg.num}</span>
                  </div>
                  <div style=${{ fontSize: '0.65rem', color: '#94a3b8', marginTop: '2px' }}>${stg.desc}</div>
                </div>
              `;
            })}
          </div>

          ${liveBlueprintStage.details && Object.keys(liveBlueprintStage.details).length > 0 && html`
            <div style=${{ background: 'rgba(0,0,0,0.3)', borderRadius: '6px', padding: '6px 10px', fontSize: '0.75rem', color: '#cbd5e1', fontFamily: 'var(--font-mono)' }}>
              ${liveBlueprintStage.details.components && html`
                <div><strong>Components (${liveBlueprintStage.details.count || liveBlueprintStage.details.components.length}):</strong> ${liveBlueprintStage.details.components.slice(0, 6).join(', ')}${liveBlueprintStage.details.components.length > 6 ? '...' : ''}</div>
              `}
              ${liveBlueprintStage.details.root_part && html`
                <div><strong>Kinematic Root:</strong> ${liveBlueprintStage.details.root_part} · <strong>Parts:</strong> ${liveBlueprintStage.details.parts_count}</div>
              `}
              ${liveBlueprintStage.details.assembly_name && html`
                <div><strong>Target:</strong> ${liveBlueprintStage.details.assembly_name} · <strong>Datum:</strong> Z=0</div>
              `}
              ${liveBlueprintStage.details.status === 'verified_viable' && html`
                <div style=${{ color: '#34d399' }}>✓ Spatial Viability Verified: 0 collisions, zero-enclosure verified, ground plane clamped.</div>
              `}
            </div>
          `}
        </div>
      `}

      <!-- Active Cycle Card (If Running) -->
      ${gymStatus?.current_cycle && html`
        <div style=${{
          padding: '1.25rem',
          background: 'rgba(59, 130, 246, 0.08)',
          border: '1px solid var(--accent-primary, #3b82f6)',
          borderRadius: '8px',
          display: 'flex',
          flexDirection: 'column',
          gap: '0.5rem',
        }}>
          <div style=${{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style=${{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--accent-primary, #3b82f6)' }}>
              ⚡ CURRENT FRONTIER CHALLENGE [CYCLE #${gymStatus.current_cycle.cycle}]
            </span>
            <span style=${{ fontSize: '0.75rem', opacity: 0.7 }}>
              Domain: ${gymStatus.current_cycle.domain} (${gymStatus.current_cycle.category})
            </span>
          </div>
          <div style=${{ fontSize: '1rem', fontWeight: 500 }}>
            ${gymStatus.current_cycle.goal}
          </div>
        </div>
      `}

      <!-- Visual Snapshot Carousel from Latest Cycle -->
      ${latestCycle && latestCycle.snapshots && Object.keys(latestCycle.snapshots).length > 0 && html`
        <div style=${{
          padding: '1.25rem',
          background: 'var(--bg-surface, #1e293b)',
          border: '1px solid var(--border-subtle, rgba(255,255,255,0.08))',
          borderRadius: '8px',
          display: 'flex',
          flexDirection: 'column',
          gap: '0.75rem',
        }}>
          <div style=${{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style=${{ fontSize: '0.9rem', fontWeight: 600 }}>
              Physical Multi-Angle Render Rig [Cycle #${latestCycle.cycle}]
            </span>
            <span style=${{ fontSize: '0.75rem', opacity: 0.6 }}>
              Blender Workbench 4-Perspective Sensory Inspection
            </span>
          </div>

          <div style=${{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '0.75rem' }}>
            ${Object.entries(latestCycle.snapshots).map(([angle, path]) => html`
              <div
                key=${angle}
                style=${{
                  background: 'rgba(0,0,0,0.4)',
                  border: '1px solid rgba(255,255,255,0.1)',
                  borderRadius: '6px',
                  overflow: 'hidden',
                  display: 'flex',
                  flexDirection: 'column',
                }}
              >
                <div style=${{ padding: '0.4rem 0.6rem', fontSize: '0.75rem', fontWeight: 600, textTransform: 'uppercase', background: 'rgba(255,255,255,0.04)' }}>
                  ${angle} view
                </div>
                <img
                  src=${`/workspaces/${path.split(/[\\/]/).pop()}`}
                  alt=${angle}
                  style=${{ width: '100%', height: '140px', objectFit: 'contain', background: '#0f172a' }}
                  onError=${(e) => { e.target.style.display = 'none'; }}
                />
              </div>
            `)}
          </div>
        </div>
      `}

      <!-- Empirical Critic Scorecard Feed -->
      <div style=${{
        flex: 1,
        background: 'var(--bg-surface, #1e293b)',
        border: '1px solid var(--border-subtle, rgba(255,255,255,0.08))',
        borderRadius: '8px',
        padding: '1.25rem',
        display: 'flex',
        flexDirection: 'column',
        gap: '0.75rem',
      }}>
        <div style=${{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style=${{ fontSize: '0.9rem', fontWeight: 600 }}>
            Empirical Critic Evaluation Feed
          </span>
          <span style=${{ fontSize: '0.75rem', opacity: 0.6 }}>
            Topological & Sensory Scorecards
          </span>
        </div>

        <div style=${{ display: 'flex', flexDirection: 'column', gap: '0.75rem', overflowY: 'auto' }}>
          ${recentCycles.length === 0 ? html`
            <div style=${{ padding: '2rem', textAlign: 'center', opacity: 0.5, fontSize: '0.85rem' }}>
              No self-play cycles recorded yet. Start 5-Hour Self-Evolution above to begin autonomous capability training.
            </div>
          ` : recentCycles.slice().reverse().map((c) => html`
            <div
              key=${c.cycle}
              style=${{
                padding: '1rem',
                background: 'rgba(0,0,0,0.25)',
                border: `1px solid ${c.passed ? 'rgba(16, 185, 129, 0.3)' : 'rgba(239, 68, 68, 0.3)'}`,
                borderRadius: '6px',
                display: 'flex',
                flexDirection: 'column',
                gap: '0.5rem',
              }}
            >
              <div style=${{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span style=${{ fontSize: '0.85rem', fontWeight: 600 }}>
                  Cycle #${c.cycle}: ${c.goal}
                </span>
                <span style=${{
                  padding: '0.2rem 0.5rem',
                  borderRadius: '4px',
                  fontSize: '0.75rem',
                  fontWeight: 'bold',
                  background: c.passed ? 'rgba(16, 185, 129, 0.2)' : 'rgba(239, 68, 68, 0.2)',
                  color: c.passed ? '#10b981' : '#ef4444',
                }}>
                  Score: ${(c.score * 100).toFixed(0)}% [${c.action}]
                </span>
              </div>

              <div style=${{ fontSize: '0.8rem', opacity: 0.85 }}>
                ${c.critique}
              </div>
            </div>
          `)}
        </div>
      </div>
    </div>
  `;
}
