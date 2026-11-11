import { React, useState, useRef } from 'https://esm.sh/react@18.3.1';
import htm from 'https://esm.sh/htm@3.1.1';
import { Icon } from '../icons.js';

const html = htm.bind(React.createElement);

const SUGGESTIONS = [
  { label: '🗡️ 3D Sword', mode: 'synthesize', prompt: 'Create a low-poly fantasy iron sword with crossguard in Blender' },
  { label: '💾 Audit Storage Drives', mode: 'react', prompt: 'Inspect all system storage drives and report their total capacity, used space, and free space' },
  { label: '📁 Find Largest Folders', mode: 'react', prompt: 'Find the top 3 largest folders across the active drives' },
  { label: '📊 System Health DAG', mode: 'dag', prompt: 'Run a full system health audit pipeline: collect telemetry into CSV, detect anomalies in Python, and write executive summary' },
];

export function Omnibar({ models, agents, onDispatch, isDispatching }) {
  const [mode, setMode] = useState('react'); // 'react' | 'synthesize' | 'dag'
  const [prompt, setPrompt] = useState('');
  const [selectedModel, setSelectedModel] = useState('qwen3.5:9b');
  const [selectedAgent, setSelectedAgent] = useState('systems_reporter');
  const textareaRef = useRef(null);

  const handleSubmit = (e) => {
    if (e) e.preventDefault();
    if (!prompt.trim() || isDispatching) return;
    onDispatch({
      mode,
      prompt: prompt.trim(),
      model: selectedModel,
      agentId: selectedAgent,
    });
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey || !e.shiftKey)) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const applySuggestion = (s) => {
    setMode(s.mode);
    setPrompt(s.prompt);
    if (textareaRef.current) textareaRef.current.focus();
  };

  return html`
    <div className="omnibar-anchor">
      <div className="omnibar-card">
        <div className="omnibar-header-row">
          <div className="mode-selector">
            <button
              className=${`mode-btn ${mode === 'react' ? 'active' : ''}`}
              onClick=${() => setMode('react')}
              title="Multi-turn Reason-Act-Observe-Reason Loop"
            >
              <${Icon} name="brain" size=${13} />
              <span>ReAct Loop</span>
            </button>

            <button
              className=${`mode-btn ${mode === 'synthesize' ? 'active' : ''}`}
              onClick=${() => setMode('synthesize')}
              title="Single-shot Gate A Specialist Synthesis"
            >
              <${Icon} name="sparkles" size=${13} />
              <span>Synthesize</span>
            </button>

            <button
              className=${`mode-btn ${mode === 'dag' ? 'active' : ''}`}
              onClick=${() => setMode('dag')}
              title="Autonomous Multi-Agent DAG Pipeline"
            >
              <${Icon} name="layers" size=${13} />
              <span>Multi-Agent DAG</span>
            </button>
          </div>

          <div style=${{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            ${mode === 'synthesize' && html`
              <select
                className="model-selector-pill"
                value=${selectedAgent}
                onChange=${(e) => setSelectedAgent(e.target.value)}
              >
                ${(agents || []).map((ag) => html`
                  <option key=${ag.agent_id} value=${ag.agent_id}>${ag.name} (${ag.domain})</option>
                `)}
              </select>
            `}

            <select
              className="model-selector-pill"
              value=${selectedModel}
              onChange=${(e) => setSelectedModel(e.target.value)}
            >
              ${(models && models.length > 0 ? models : ['qwen3.5:9b', 'qwen3:14b', 'phi3:mini']).map((m) => html`
                <option key=${m} value=${m}>🧠 ${m}</option>
              `)}
            </select>
          </div>
        </div>

        <div className="omnibar-input-row">
          <textarea
            ref=${textareaRef}
            className="omnibar-textarea"
            placeholder=${
              mode === 'react'
                ? "Enter multi-step autonomous goal (e.g. 'Audit G:\\ drive and find largest folder')..."
                : mode === 'dag'
                ? "Describe multi-agent workflow to decompose into a DAG..."
                : "Describe artifact to synthesize (3D Mesh, Python Code, CSV Data, Report)..."
            }
            value=${prompt}
            onChange=${(e) => setPrompt(e.target.value)}
            onKeyDown=${handleKeyDown}
            rows="1"
          />

          <button
            className="omnibar-dispatch-btn"
            onClick=${handleSubmit}
            disabled=${!prompt.trim() || isDispatching}
          >
            ${isDispatching
              ? html`
                  <${Icon} name="refresh" size=${14} />
                  <span>Executing...</span>
                `
              : html`
                  <${Icon} name="play" size=${14} />
                  <span>Dispatch</span>
                `}
          </button>
        </div>

        <div className="omnibar-suggestions">
          <span style=${{ fontSize: '11px', color: '#64748b' }}>Suggestions:</span>
          ${SUGGESTIONS.map((s, idx) => html`
            <button
              key=${idx}
              className="suggestion-chip"
              onClick=${() => applySuggestion(s)}
            >
              ${s.label}
            </button>
          `)}
        </div>
      </div>
    </div>
  `;
}
