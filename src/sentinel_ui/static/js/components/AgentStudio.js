import { useState } from 'https://esm.sh/react@18.3.1';
import { html } from '../html.js';
import { Icon } from '../icons.js';

export function AgentStudio({ agents, onPublishAgent, onDraftAgent }) {
  const [showModal, setShowModal] = useState(false);
  const [formData, setFormData] = useState({
    agent_id: '',
    name: '',
    domain: 'code',
    tools: 'system_filesystem_inspect, run_appcontainer_code',
    system_prompt: 'You are an autonomous Gate A specialist.',
    temperature: 0.2,
    timeout_seconds: 60,
  });

  const handleSubmit = (e) => {
    e.preventDefault();
    const manifest = {
      ...formData,
      tools: formData.tools.split(',').map((t) => t.trim()).filter(Boolean),
    };
    onPublishAgent(manifest);
    setShowModal(false);
  };

  return html`
    <div style=${{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      <div className="card-glass">
        <div className="card-header">
          <div className="card-title-group">
            <div className="card-icon">
              <${Icon} name="brain" size=${16} />
            </div>
            <div>
              <div className="card-title">Gate A Agent Registry</div>
              <div className="card-subtitle">Specialized cognitive personas · Fenced organ boundaries · Sandboxed execution (${(agents || []).length} registered)</div>
            </div>
          </div>

          <button className="btn btn-primary" onClick=${() => setShowModal(true)}>
            <${Icon} name="sparkles" size=${13} />
            <span>Publish New Agent</span>
          </button>
        </div>

        <div className="spatial-grid-2col">
          ${(agents || []).map((ag) => {
            const agentId = ag.id || ag.agent_id;
            const domain = ag.manifest?.capabilities?.[0] || ag.domain || 'code';
            const tools = ag.manifest?.allowed_organs || ag.tools || [];
            const desc = ag.manifest?.description || ag.description || '';
            const status = ag.status || 'Published';

            return html`
              <div
                key=${agentId}
                className="card-glass"
                style=${{ padding: '18px', background: 'rgba(255, 255, 255, 0.02)' }}
              >
                <div style=${{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
                  <div style=${{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span style=${{ fontSize: '15px', fontWeight: 600, color: '#f8fafc' }}>${ag.name}</span>
                    <span className=${`domain-badge ${domain}`}>${domain}</span>
                  </div>
                  <span className="pill success">${status}</span>
                </div>

                <div style=${{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: '#64748b', marginBottom: '8px' }}>
                  ID: ${agentId}
                </div>

                ${desc && html`
                  <div style=${{ fontSize: '12px', color: '#94a3b8', marginBottom: '12px', lineHeight: 1.5 }}>
                    ${desc}
                  </div>
                `}

                <div style=${{ marginBottom: '14px' }}>
                  <div style=${{ fontSize: '11px', color: '#64748b', marginBottom: '6px' }}>Organ Privileges (${tools.length}):</div>
                  <div style=${{ display: 'flex', flexWrap: 'wrap', gap: '5px' }}>
                    ${tools.map((tool, idx) => html`
                      <span
                        key=${idx}
                        style=${{
                          fontFamily: 'var(--font-mono)',
                          fontSize: '10px',
                          background: 'rgba(255, 255, 255, 0.04)',
                          border: '1px solid rgba(255, 255, 255, 0.08)',
                          padding: '2px 6px',
                          borderRadius: '4px',
                          color: '#cbd5e1',
                        }}
                      >
                        ${tool}
                      </span>
                    `)}
                  </div>
                </div>

                <div style=${{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '11px', color: '#64748b' }}>
                  <span>Memory Cap: <strong>${ag.manifest?.max_memory_mb || 100} MB</strong></span>
                  <span>CPU Cap: <strong>${ag.manifest?.max_cpu_percent || 12.5}%</strong></span>
                </div>
              </div>
            `;
          })}
        </div>
      </div>

      <!-- Publish Agent Modal -->
      ${showModal && html`
        <div className="modal-overlay" onClick=${() => setShowModal(false)}>
          <div className="modal-content" onClick=${(e) => e.stopPropagation()}>
            <div className="modal-header">
              <span style=${{ fontSize: '16px', fontWeight: 600, color: '#fff' }}>Publish Gate A Agent Manifest</span>
              <button className="btn-icon" onClick=${() => setShowModal(false)}>
                <${Icon} name="close" size=${16} />
              </button>
            </div>

            <form onSubmit=${handleSubmit}>
              <div className="modal-body">
                <div className="form-group">
                  <label className="form-label">Agent ID (slug)</label>
                  <input
                    type="text"
                    className="form-input"
                    value=${formData.agent_id}
                    onChange=${(e) => setFormData({ ...formData, agent_id: e.target.value })}
                    placeholder="e.g. storage_auditor"
                    required
                  />
                </div>

                <div className="form-group">
                  <label className="form-label">Display Name</label>
                  <input
                    type="text"
                    className="form-input"
                    value=${formData.name}
                    onChange=${(e) => setFormData({ ...formData, name: e.target.value })}
                    placeholder="e.g. Storage Auditor Specialist"
                    required
                  />
                </div>

                <div className="form-group">
                  <label className="form-label">Specialist Domain</label>
                  <select
                    className="form-select"
                    value=${formData.domain}
                    onChange=${(e) => setFormData({ ...formData, domain: e.target.value })}
                  >
                    <option value="code">code (Python)</option>
                    <option value="3d">3d (Blender Mesh)</option>
                    <option value="data">data (CSV & Metrics)</option>
                    <option value="report">report (Systems Executive)</option>
                  </select>
                </div>

                <div className="form-group">
                  <label className="form-label">Allowed Tools / Organs (comma separated)</label>
                  <input
                    type="text"
                    className="form-input"
                    value=${formData.tools}
                    onChange=${(e) => setFormData({ ...formData, tools: e.target.value })}
                    placeholder="e.g. system_filesystem_inspect, run_appcontainer_code"
                    required
                  />
                </div>

                <div className="form-group">
                  <label className="form-label">System Prompt</label>
                  <textarea
                    className="form-textarea"
                    rows="3"
                    value=${formData.system_prompt}
                    onChange=${(e) => setFormData({ ...formData, system_prompt: e.target.value })}
                  />
                </div>
              </div>

              <div className="modal-footer">
                <button type="button" className="btn btn-secondary" onClick=${() => setShowModal(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary">
                  Publish Manifest
                </button>
              </div>
            </form>
          </div>
        </div>
      `}
    </div>
  `;
}
