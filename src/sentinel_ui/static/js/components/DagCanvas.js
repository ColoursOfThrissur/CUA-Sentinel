import { useState } from 'https://esm.sh/react@18.3.1';
import { html } from '../html.js';
import { Icon } from '../icons.js';

export function DagCanvas({
  templates,
  activeRuns,
  selectedRun,
  onSelectRun,
  onRunTemplate,
  onCancelDag,
  onOpenViewport,
  isDispatching,
}) {
  return html`
    <div style=${{ display: 'flex', flexDirection: 'column', gap: '28px' }}>
      <!-- Header: Production DAG Pipeline Templates -->
      <div className="card-glass">
        <div className="card-header">
          <div className="card-title-group">
            <div className="card-icon">
              <${Icon} name="layers" size=${16} />
            </div>
            <div>
              <div className="card-title">Multi-Agent DAG Pipeline Templates</div>
              <div className="card-subtitle">Concurrent wave execution · Structured artifact handoffs · Fault isolation</div>
            </div>
          </div>
        </div>

        <div className="spatial-grid-2col">
          ${(templates || []).map((tpl) => {
            const templateId = tpl.id || tpl.template_name || '';
            const templateTitle = tpl.name || (templateId ? templateId.replace(/_/g, ' ').toUpperCase() : 'Pipeline Template');
            const stepsList = tpl.steps || [];

            return html`
              <div
                key=${templateId}
                className="card-glass clickable"
                style=${{ padding: '16px', background: 'rgba(255, 255, 255, 0.02)' }}
              >
                <div style=${{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
                  <span style=${{ fontSize: '14px', fontWeight: 600, color: '#f8fafc' }}>
                    ${templateTitle}
                  </span>
                  <span className="pill pending">${stepsList.length} Steps</span>
                </div>

                <div style=${{ fontSize: '12px', color: '#94a3b8', marginBottom: '14px' }}>
                  ${tpl.description}
                </div>

                <div style=${{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <div style=${{ display: 'flex', gap: '6px' }}>
                    ${stepsList.map((st, i) => html`
                      <span key=${i} className=${`domain-badge ${st.domain || 'report'}`}>
                        ${st.agent_id}
                      </span>
                    `)}
                  </div>

                  <button
                    className="btn btn-primary"
                    style=${{ padding: '5px 12px', fontSize: '11px' }}
                    disabled=${isDispatching}
                    onClick=${() => onRunTemplate(templateId)}
                  >
                    <${Icon} name="play" size=${12} />
                    <span>Launch Pipeline</span>
                  </button>
                </div>
              </div>
            `;
          })}
        </div>
      </div>

      <!-- Historical / Active Runs Selector Row -->
      ${(activeRuns && activeRuns.length > 0) && html`
        <div style=${{ display: 'flex', alignItems: 'center', gap: '10px', overflowX: 'auto', padding: '4px 0' }}>
          <span style=${{ fontSize: '12px', color: '#64748b', whiteSpace: 'nowrap' }}>Pipeline Runs:</span>
          ${activeRuns.map((r) => html`
            <button
              key=${r.id}
              className=${`nav-pill-btn ${(selectedRun?.id === r.id) ? 'active' : ''}`}
              onClick=${() => onSelectRun(r)}
            >
              <span className=${`pill ${r.state}`} style=${{ fontSize: '9px', padding: '1px 6px' }}>${r.state}</span>
              <span>${r.name || r.id}</span>
            </button>
          `)}
        </div>
      `}

      <!-- Execution Canvas: Selected Pipeline Run -->
      <div className="card-glass" style=${{ minHeight: '400px' }}>
        <div className="card-header">
          <div className="card-title-group">
            <div className="card-icon">
              <${Icon} name="activity" size=${16} />
            </div>
            <div>
              <div className="card-title">
                ${selectedRun ? (selectedRun.name || selectedRun.id) : 'Active Pipeline Graph'}
              </div>
              <div className="card-subtitle">
                ${selectedRun ? `Run ID: ${selectedRun.id} · Wave propagation & artifact flow` : 'Select or trigger a DAG pipeline'}
              </div>
            </div>
          </div>

          ${selectedRun && html`
            <div style=${{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <span className=${`pill ${selectedRun.state}`}>State: ${selectedRun.state}</span>
              ${selectedRun.state === 'Running' && html`
                <button
                  className="btn btn-danger"
                  style=${{ padding: '4px 10px', fontSize: '11px' }}
                  onClick=${() => onCancelDag(selectedRun.id)}
                >
                  <${Icon} name="square" size=${12} />
                  <span>Cancel Pipeline</span>
                </button>
              `}
            </div>
          `}
        </div>

        ${!selectedRun && (!activeRuns || activeRuns.length === 0) && html`
          <div className="empty-state">
            <div className="empty-state-icon">
              <${Icon} name="layers" size=${36} />
            </div>
            <div className="empty-state-text">
              No active or historical DAG runs found. Launch one of the templates above or dispatch a multi-agent goal from the Omnibar.
            </div>
          </div>
        `}

        ${selectedRun && html`
          <div className="dag-canvas-board">
            <div className="dag-wave-row">
              <div className="dag-wave-header">
                <${Icon} name="sparkles" size=${13} />
                <span>Wave Execution Nodes (${(selectedRun.steps || []).length} steps)</span>
              </div>

              <div className="dag-nodes-cluster">
                ${(selectedRun.steps || []).map((step) => {
                  const artifact = step.artifact_filename || step.artifact || null;
                  return html`
                    <div key=${step.step_id || step.id} className=${`dag-node-card ${step.state}`}>
                      <div style=${{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                        <span className=${`domain-badge ${step.domain || 'report'}`}>${step.agent_id}</span>
                        <span className=${`pill ${step.state}`} style=${{ fontSize: '10px', padding: '2px 7px' }}>
                          ${step.state}
                        </span>
                      </div>

                      <div className="dag-node-title">${step.goal}</div>

                      <div className="dag-node-meta">
                        <span style=${{ color: '#64748b' }}>
                          Deps: ${(step.dependencies && step.dependencies.length > 0) ? step.dependencies.join(', ') : 'None (Wave 1)'}
                        </span>
                        ${step.state === 'Running' && html`
                          <span style=${{ color: 'var(--accent-cyan)' }}>Active...</span>
                        `}
                      </div>

                      ${artifact && html`
                        <div style=${{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: '6px' }}>
                          <span className="dag-node-contract">${artifact}</span>
                          <button
                            className="btn btn-secondary"
                            style=${{ padding: '2px 8px', fontSize: '10px' }}
                            onClick=${() => onOpenViewport(artifact)}
                          >
                            <${Icon} name="eye" size=${10} />
                            <span>View</span>
                          </button>
                        </div>
                      `}
                    </div>
                  `;
                })}
              </div>
            </div>
          </div>
        `}
      </div>
    </div>
  `;
}
