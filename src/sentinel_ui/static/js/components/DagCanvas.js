import { useState } from 'https://esm.sh/react@18.3.1';
import { html } from '../html.js';
import { Icon } from '../icons.js';

export function DagCanvas({
  templates,
  activeRuns,
  selectedRun,
  onSelectRun,
  onRunTemplate,
  onDispatchCustomPipeline,
  onCancelDag,
  onOpenViewport,
  isDispatching,
}) {
  const [showBuilder, setShowBuilder] = useState(false);
  const [pipelineName, setPipelineName] = useState('Custom Multi-Agent Pipeline');
  const [pipelineDesc, setPipelineDesc] = useState('Operator configured multi-stage pipeline');
  const [customSteps, setCustomSteps] = useState([
    {
      step_id: 'step_1_collect',
      agent_id: 'data_analyst',
      domain: 'data',
      goal: 'Generate an edge metrics dataset in CSV with 10 rows and columns timestamp, device_id, temperature, cpu_pct',
      dependencies: [],
    },
    {
      step_id: 'step_2_analyze',
      agent_id: 'code_engineer',
      domain: 'code',
      goal: 'Write Python code to inspect the CSV from step_1, detect anomalous temperature spikes, and output results',
      dependencies: ['step_1_collect'],
    },
  ]);

  const addStep = () => {
    const nextIdx = customSteps.length + 1;
    const prevStepId = customSteps.length > 0 ? customSteps[customSteps.length - 1].step_id : null;
    setCustomSteps([
      ...customSteps,
      {
        step_id: `step_${nextIdx}_task`,
        agent_id: 'systems_reporter',
        domain: 'report',
        goal: 'Summarize previous outputs and write an executive briefing',
        dependencies: prevStepId ? [prevStepId] : [],
      },
    ]);
  };

  const removeStep = (idx) => {
    if (customSteps.length <= 1) return;
    const stepToRemove = customSteps[idx].step_id;
    const updated = customSteps.filter((_, i) => i !== idx).map((s) => ({
      ...s,
      dependencies: (s.dependencies || []).filter((d) => d !== stepToRemove),
    }));
    setCustomSteps(updated);
  };

  const updateStep = (idx, field, val) => {
    const updated = [...customSteps];
    updated[idx] = { ...updated[idx], [field]: val };
    // Auto-align domain if agent changed
    if (field === 'agent_id') {
      if (val === 'data_analyst') updated[idx].domain = 'data';
      else if (val === 'code_engineer') updated[idx].domain = 'code';
      else if (val === 'blender_artisan') updated[idx].domain = '3d';
      else if (val === 'systems_reporter') updated[idx].domain = 'report';
    }
    setCustomSteps(updated);
  };

  const toggleDependency = (stepIdx, depId) => {
    const updated = [...customSteps];
    const currentDeps = updated[stepIdx].dependencies || [];
    if (currentDeps.includes(depId)) {
      updated[stepIdx].dependencies = currentDeps.filter((d) => d !== depId);
    } else {
      updated[stepIdx].dependencies = [...currentDeps, depId];
    }
    setCustomSteps(updated);
  };

  const handleLaunchCustom = (e) => {
    e.preventDefault();
    if (onDispatchCustomPipeline) {
      onDispatchCustomPipeline({
        name: pipelineName,
        description: pipelineDesc,
        steps: customSteps,
      });
      setShowBuilder(false);
    }
  };

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
              <div className="card-title">Multi-Agent DAG Pipeline Orchestration</div>
              <div className="card-subtitle">Concurrent wave execution · Structured artifact handoffs · Fault isolation</div>
            </div>
          </div>

          <button className="btn btn-primary" onClick=${() => setShowBuilder(true)}>
            <${Icon} name="sparkles" size=${13} />
            <span>Build Custom Pipeline</span>
          </button>
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
                    <span>Launch Template</span>
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
              No active or historical DAG runs found. Launch one of the templates above or build a custom pipeline.
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
                  const rawArt = step.artifact_filename || step.output_artifact || step.artifact || null;
                  const artifact = rawArt ? rawArt.split(/[/\\]/).pop() : null;
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

      <!-- Custom DAG Builder Modal -->
      ${showBuilder && html`
        <div className="modal-overlay" onClick=${() => setShowBuilder(false)}>
          <div className="modal-content" style=${{ maxWidth: '1050px' }} onClick=${(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div style=${{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <${Icon} name="layers" size=${18} />
                <span style=${{ fontSize: '16px', fontWeight: 600, color: '#fff' }}>Interactive Custom DAG Pipeline Builder</span>
              </div>
              <button className="btn-icon" onClick=${() => setShowBuilder(false)}>
                <${Icon} name="close" size=${16} />
              </button>
            </div>

            <form onSubmit=${handleLaunchCustom}>
              <div className="modal-body" style=${{ display: 'flex', flexDirection: 'column', gap: '18px' }}>
                <div style=${{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '14px' }}>
                  <div className="form-group" style=${{ margin: 0 }}>
                    <label className="form-label">Pipeline Name</label>
                    <input
                      type="text"
                      className="form-input"
                      value=${pipelineName}
                      onChange=${(e) => setPipelineName(e.target.value)}
                      required
                    />
                  </div>
                  <div className="form-group" style=${{ margin: 0 }}>
                    <label className="form-label">Description</label>
                    <input
                      type="text"
                      className="form-input"
                      value=${pipelineDesc}
                      onChange=${(e) => setPipelineDesc(e.target.value)}
                      required
                    />
                  </div>
                </div>

                <div style=${{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderTop: '1px solid var(--border-glass)', paddingTop: '14px' }}>
                  <span style=${{ fontSize: '13px', fontWeight: 600, color: 'var(--accent-cyan)' }}>
                    Pipeline Steps (${customSteps.length})
                  </span>
                  <button type="button" className="btn btn-secondary" onClick=${addStep}>
                    <${Icon} name="sparkles" size=${12} />
                    <span>+ Add Step</span>
                  </button>
                </div>

                <div style=${{ display: 'flex', flexDirection: 'column', gap: '14px', maxHeight: '420px', overflowY: 'auto' }}>
                  ${customSteps.map((step, idx) => {
                    const availablePredecessors = customSteps.slice(0, idx);
                    return html`
                      <div
                        key=${idx}
                        className="card-glass"
                        style=${{ padding: '16px', background: 'rgba(255, 255, 255, 0.02)', position: 'relative' }}
                      >
                        <div style=${{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
                          <span style=${{ fontSize: '12px', fontWeight: 700, color: 'var(--accent-primary)' }}>
                            Stage ${idx + 1}: ${step.step_id}
                          </span>
                          ${customSteps.length > 1 && html`
                            <button
                              type="button"
                              className="btn btn-danger"
                              style=${{ padding: '2px 8px', fontSize: '10px' }}
                              onClick=${() => removeStep(idx)}
                            >
                              Remove
                            </button>
                          `}
                        </div>

                        <div style=${{ display: 'grid', gridTemplateColumns: '1.2fr 1fr 1fr', gap: '10px', marginBottom: '10px' }}>
                          <div className="form-group" style=${{ margin: 0 }}>
                            <label className="form-label">Step Identifier</label>
                            <input
                              type="text"
                              className="form-input"
                              value=${step.step_id}
                              onChange=${(e) => updateStep(idx, 'step_id', e.target.value)}
                              required
                            />
                          </div>

                          <div className="form-group" style=${{ margin: 0 }}>
                            <label className="form-label">Gate A Agent</label>
                            <select
                              className="form-select"
                              value=${step.agent_id}
                              onChange=${(e) => updateStep(idx, 'agent_id', e.target.value)}
                            >
                              <option value="data_analyst">Data Analyst</option>
                              <option value="code_engineer">Software Engineer</option>
                              <option value="blender_artisan">3D Procedural Artisan</option>
                              <option value="systems_reporter">Executive Systems Reporter</option>
                            </select>
                          </div>

                          <div className="form-group" style=${{ margin: 0 }}>
                            <label className="form-label">Domain Artifact</label>
                            <select
                              className="form-select"
                              value=${step.domain}
                              onChange=${(e) => updateStep(idx, 'domain', e.target.value)}
                            >
                              <option value="data">data (.csv)</option>
                              <option value="code">code (.py)</option>
                              <option value="3d">3d (.obj)</option>
                              <option value="report">report (.md)</option>
                            </select>
                          </div>
                        </div>

                        <div className="form-group" style=${{ margin: '0 0 10px 0' }}>
                          <label className="form-label">Step Goal Instruction</label>
                          <textarea
                            className="form-textarea"
                            rows="2"
                            value=${step.goal}
                            onChange=${(e) => updateStep(idx, 'goal', e.target.value)}
                            placeholder="Exact task goal instruction for this agent..."
                            required
                          />
                        </div>

                        ${availablePredecessors.length > 0 && html`
                          <div>
                            <label className="form-label" style=${{ marginBottom: '4px', display: 'block' }}>
                              Predecessor Dependencies (Wave Wait Fence):
                            </label>
                            <div style=${{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                              ${availablePredecessors.map((prev) => {
                                const isChecked = (step.dependencies || []).includes(prev.step_id);
                                return html`
                                  <button
                                    key=${prev.step_id}
                                    type="button"
                                    className=${`nav-pill-btn ${isChecked ? 'active' : ''}`}
                                    style=${{ fontSize: '11px', padding: '3px 10px' }}
                                    onClick=${() => toggleDependency(idx, prev.step_id)}
                                  >
                                    ${isChecked ? '✓ ' : '+ '} Depends on ${prev.step_id}
                                  </button>
                                `;
                              })}
                            </div>
                          </div>
                        `}
                      </div>
                    `;
                  })}
                </div>
              </div>

              <div className="modal-footer">
                <button type="button" className="btn btn-secondary" onClick=${() => setShowBuilder(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary" disabled=${isDispatching}>
                  <${Icon} name="play" size=${13} />
                  <span>Execute Custom Pipeline</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      `}
    </div>
  `;
}
