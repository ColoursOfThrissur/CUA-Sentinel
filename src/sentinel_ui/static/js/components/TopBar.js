import { html } from '../html.js';
import { Icon } from '../icons.js';

export function TopBar({ activeTab, onTabChange, telemetry, onRefresh, refreshing }) {
  const ramAvailable = telemetry?.system?.available_ram_mb || 0;
  const ramFloor = telemetry?.ram_floor_mb || 2500;
  const lease = telemetry?.lease?.active_monotonic_lease ?? '--';
  const mistakeCount = telemetry?.mistakes_learned || 0;
  const skillCount = telemetry?.skills_in_bank || 0;

  return html`
    <header className="topbar-spatial">
      <div className="topbar-brand" onClick=${() => onTabChange('command')}>
        <div className="brand-dot"></div>
        <span className="brand-name">SENTINEL</span>
        <span className="brand-sub">Runtime OS</span>
      </div>

      <nav className="nav-pills">
        <button
          className=${`nav-pill-btn ${activeTab === 'command' ? 'active' : ''}`}
          onClick=${() => onTabChange('command')}
        >
          <${Icon} name="terminal" size=${14} />
          <span>Command Deck</span>
        </button>

        <button
          className=${`nav-pill-btn ${activeTab === 'dag' ? 'active' : ''}`}
          onClick=${() => onTabChange('dag')}
        >
          <${Icon} name="layers" size=${14} />
          <span>Pipelines & DAG</span>
        </button>

        <button
          className=${`nav-pill-btn ${activeTab === 'agents' ? 'active' : ''}`}
          onClick=${() => onTabChange('agents')}
        >
          <${Icon} name="brain" size=${14} />
          <span>Agent Studio</span>
        </button>

        <button
          className=${`nav-pill-btn ${activeTab === 'observability' ? 'active' : ''}`}
          onClick=${() => onTabChange('observability')}
        >
          <${Icon} name="activity" size=${14} />
          <span>Observability</span>
        </button>
      </nav>

      <div className="telemetry-cluster">
        <div className="metric-pill" title="Hardware RAM Floor vs Target Floor">
          <span className="label">RAM</span>
          <span className="value highlight">${Math.round(ramAvailable)}MB</span>
          <span className="label">/ ${ramFloor}MB</span>
        </div>

        <div className="metric-pill" title="AT-B-10 Monotonic Lease Counter">
          <span className="label">Lease</span>
          <span className="value">#${lease}</span>
        </div>

        <div className="metric-pill" title="Episodic Mistakes Distilled into Memory">
          <span className="label">Mistakes</span>
          <span className="value">${mistakeCount}</span>
        </div>

        <div className="metric-pill" title="Distilled Skills in Dynamic Bank">
          <span className="label">Skills</span>
          <span className="value">${skillCount}</span>
        </div>

        <button 
          className="btn-icon" 
          onClick=${onRefresh} 
          title="Refresh Telemetry"
          style=${{ animation: refreshing ? 'spin 1s infinite linear' : 'none' }}
        >
          <${Icon} name="refresh" size=${14} />
        </button>
      </div>
    </header>
  `;
}
