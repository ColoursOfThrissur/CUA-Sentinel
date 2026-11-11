import { html } from '../html.js';
import { Icon } from '../icons.js';

export function CommandDeck({
  reactTrajectory,
  activeTasks,
  onCancelTask,
  onOpenViewport,
  isExecutingReAct,
}) {
  return html`
    <div className="spatial-grid-2col">
      <!-- Left Column: ReAct Trajectory Stream -->
      <div className="card-glass" style=${{ minHeight: '500px' }}>
        <div className="card-header">
          <div className="card-title-group">
            <div className="card-icon">
              <${Icon} name="brain" size=${16} />
            </div>
            <div>
              <div className="card-title">Autonomous ReAct Trajectory</div>
              <div className="card-subtitle">Reason · Act · Observe · Reason inner execution trace</div>
            </div>
          </div>
          ${isExecutingReAct && html`
            <div className="pill running">
              <${Icon} name="activity" size=${12} />
              <span>Multi-Turn Active</span>
            </div>
          `}
        </div>

        ${!reactTrajectory && !isExecutingReAct && html`
          <div className="empty-state">
            <div className="empty-state-icon">
              <${Icon} name="terminal" size=${36} />
            </div>
            <div className="empty-state-text">
              No active ReAct trajectory. Select <strong>ReAct Loop</strong> in the Omnibar below and dispatch a goal to watch the agent reason in real time.
            </div>
          </div>
        `}

        ${isExecutingReAct && !reactTrajectory && html`
          <div className="empty-state">
            <div className="empty-state-icon" style=${{ animation: 'spin 1.5s infinite linear' }}>
              <${Icon} name="refresh" size=${32} />
            </div>
            <div className="empty-state-text">
              Agent is reasoning and executing tools in the AppContainer sandbox...
            </div>
          </div>
        `}

        ${reactTrajectory && html`
          <div className="trajectory-container">
            <div style=${{ fontSize: '12px', color: '#94a3b8', marginBottom: '8px' }}>
              Goal: <strong style=${{ color: '#fff' }}>${reactTrajectory.goal}</strong>
            </div>

            ${(reactTrajectory.trajectory || []).map((step, idx) => html`
              <div key=${idx} className="trajectory-step">
                <div className=${`step-node-dot ${step.action ? 'action-dot' : ''}`}></div>
                
                <div className="turn-header">
                  <span className="turn-pill">Turn ${step.turn || idx + 1}</span>
                  ${step.action && html`
                    <span style=${{ fontSize: '11px', color: '#64748b' }}>Organ Execution</span>
                  `}
                </div>

                ${step.thought && html`
                  <div className="thought-card">
                    <div className="thought-header">
                      <${Icon} name="brain" size=${12} />
                      <span>Reasoning</span>
                    </div>
                    <div className="thought-content">${step.thought}</div>
                  </div>
                `}

                ${step.action && html`
                  <div className="action-card">
                    <div className="action-header">
                      <span>Motor Action</span>
                      <span className="tool-name-badge">${step.action.tool}</span>
                    </div>
                    <div className="action-params-preview">
                      ${JSON.stringify(step.action.parameters, null, 2)}
                    </div>
                  </div>
                `}

                ${step.observation !== undefined && html`
                  <div className="observation-card">
                    <div className="observation-header">
                      <span>Telemetry Observation</span>
                      <span>Output</span>
                    </div>
                    <div className="observation-body">
                      ${typeof step.observation === 'object'
                        ? JSON.stringify(step.observation, null, 2)
                        : String(step.observation)}
                    </div>
                  </div>
                `}
              </div>
            `)}

            ${reactTrajectory.final_answer && html`
              <div className="final-answer-card">
                <div className="final-header">
                  <${Icon} name="check" size=${16} />
                  <span>Synthesized Solution</span>
                </div>
                <div className="final-content">${reactTrajectory.final_answer}</div>
                ${reactTrajectory.artifact && html`
                  <div style=${{ marginTop: '14px', display: 'flex', gap: '8px' }}>
                    <button
                      className="btn btn-secondary"
                      onClick=${() => onOpenViewport(reactTrajectory.artifact)}
                    >
                      <${Icon} name="eye" size=${13} />
                      <span>Inspect Artifact</span>
                    </button>
                    <a
                      className="btn btn-primary"
                      href=${`/workspaces/${reactTrajectory.artifact}`}
                      download
                    >
                      <${Icon} name="download" size=${13} />
                      <span>Download</span>
                    </a>
                  </div>
                `}
              </div>
            `}
          </div>
        `}
      </div>

      <!-- Right Column: Recent Tasks & State Machine Transitions -->
      <div className="card-glass" style=${{ minHeight: '500px' }}>
        <div className="card-header">
          <div className="card-title-group">
            <div className="card-icon">
              <${Icon} name="activity" size=${16} />
            </div>
            <div>
              <div className="card-title">Task Lifecycle Feed</div>
              <div className="card-subtitle">AT-B-05 State Machine · Monotonic Leases · Verification Gates</div>
            </div>
          </div>
        </div>

        ${(!activeTasks || activeTasks.length === 0) && html`
          <div className="empty-state">
            <div className="empty-state-icon">
              <${Icon} name="fileText" size=${36} />
            </div>
            <div className="empty-state-text">No recent tasks found in SQLite state store.</div>
          </div>
        `}

        <div style=${{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          ${(activeTasks || []).map((task) => html`
            <div
              key=${task.task_id}
              className="card-glass"
              style=${{ padding: '14px', background: 'rgba(255, 255, 255, 0.02)' }}
            >
              <div style=${{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
                <span style=${{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: '#64748b' }}>
                  ${task.task_id}
                </span>
                <div style=${{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <span className=${`pill ${task.state}`}>${task.state}</span>
                  ${['Running', 'Synthesizing', 'Verifying'].includes(task.state) && html`
                    <button
                      className="btn btn-danger"
                      style=${{ padding: '2px 8px', fontSize: '10px' }}
                      onClick=${() => onCancelTask(task.task_id)}
                      title="Cancel Task and Drain Process Tree"
                    >
                      <${Icon} name="square" size=${10} />
                      <span>Cancel</span>
                    </button>
                  `}
                </div>
              </div>

              <div style=${{ fontSize: '13px', fontWeight: 500, color: '#f8fafc', marginBottom: '8px' }}>
                ${task.goal || task.title}
              </div>

              <div style=${{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '11px', color: '#94a3b8' }}>
                <div style=${{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span className=${`domain-badge ${task.domain || 'report'}`}>${task.domain || 'general'}</span>
                  <span>Attempt: <strong>${task.attempts || 1}/3</strong></span>
                </div>

                ${task.artifact && html`
                  <div style=${{ display: 'flex', gap: '6px' }}>
                    <button
                      className="btn btn-secondary"
                      style=${{ padding: '3px 8px', fontSize: '11px' }}
                      onClick=${() => onOpenViewport(task.artifact)}
                    >
                      <${Icon} name="eye" size=${11} />
                      <span>Preview</span>
                    </button>
                    <a
                      className="btn btn-secondary"
                      style=${{ padding: '3px 8px', fontSize: '11px' }}
                      href=${`/workspaces/${task.artifact}`}
                      download
                    >
                      <${Icon} name="download" size=${11} />
                    </a>
                  </div>
                `}
              </div>
            </div>
          `)}
        </div>
      </div>
    </div>
  `;
}
