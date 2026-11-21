import { html } from '../html.js';
import { Icon } from '../icons.js';

export function CommandDeck({
  reactTrajectory,
  activeTasks,
  selectedTaskId,
  selectedTaskTrace,
  onSelectTask,
  liveBlueprintStage,
  onCancelTask,
  onOpenViewport,
  isExecutingReAct,
}) {
  return html`
    <div style=${{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      ${liveBlueprintStage && html`
        <div className="card-glass" style=${{ padding: '16px 20px', border: '1px solid rgba(56, 189, 248, 0.3)', background: 'linear-gradient(135deg, rgba(56, 189, 248, 0.05) 0%, rgba(168, 85, 247, 0.05) 100%)' }}>
          <div style=${{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px', flexWrap: 'wrap', gap: '8px' }}>
            <div style=${{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <div style=${{ width: '28px', height: '28px', borderRadius: '6px', background: 'rgba(56, 189, 248, 0.2)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#38bdf8' }}>
                <${Icon} name="sparkles" size=${16} />
              </div>
              <div>
                <div style=${{ fontSize: '14px', fontWeight: 600, color: '#f8fafc' }}>
                  Progressive LoD Blueprint Pipeline (Live Telemetry)
                </div>
                <div style=${{ fontSize: '11.5px', color: '#94a3b8' }}>
                  Stage ${liveBlueprintStage.stage}: ${liveBlueprintStage.stage_name}
                </div>
              </div>
            </div>
            <div className=${`pill ${liveBlueprintStage.status === 'running' ? 'running' : 'success'}`}>
              ${liveBlueprintStage.status === 'running' ? 'Generating Phase...' : 'Phase Complete'}
            </div>
          </div>

          <!-- 5-Stage Visual Progress Stepper -->
          <div style=${{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: '8px', marginBottom: '12px' }}>
            ${[
              { num: 1.0, title: 'Anatomy', desc: 'Hardware Discovery' },
              { num: 2.0, title: 'Kinematics', desc: 'Parent-Child Tree' },
              { num: 3.0, title: 'Dimensions', desc: 'Metric Offsets' },
              { num: 3.5, title: 'Viability', desc: 'ReAct CAD Audit' },
              { num: 4.0, title: 'Materials', desc: 'PBR Shaders' },
            ].map((stg) => {
              const currentStageNum = parseFloat(liveBlueprintStage.stage) || 0;
              const isPast = currentStageNum > stg.num;
              const isCurrent = Math.abs(currentStageNum - stg.num) < 0.3;
              return html`
                <div
                  key=${stg.num}
                  style=${{
                    background: isCurrent ? 'rgba(56, 189, 248, 0.15)' : isPast ? 'rgba(16, 185, 129, 0.1)' : 'rgba(255, 255, 255, 0.02)',
                    border: `1px solid ${isCurrent ? '#38bdf8' : isPast ? '#10b981' : 'rgba(255, 255, 255, 0.08)'}`,
                    borderRadius: '6px',
                    padding: '8px 10px',
                    transition: 'all 0.3s ease',
                  }}
                >
                  <div style=${{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '2px' }}>
                    <span style=${{ fontSize: '11px', fontWeight: 600, color: isCurrent ? '#38bdf8' : isPast ? '#34d399' : '#64748b' }}>
                      ${stg.title}
                    </span>
                    <span style=${{ fontSize: '10px', color: '#94a3b8' }}>S${stg.num}</span>
                  </div>
                  <div style=${{ fontSize: '10px', color: '#94a3b8' }}>${stg.desc}</div>
                </div>
              `;
            })}
          </div>

          <!-- Live Stage Details Breakdown -->
          ${liveBlueprintStage.details && Object.keys(liveBlueprintStage.details).length > 0 && html`
            <div style=${{ background: 'rgba(0,0,0,0.3)', borderRadius: '6px', padding: '8px 12px', fontSize: '11.5px', color: '#cbd5e1', fontFamily: 'var(--font-mono)' }}>
              ${liveBlueprintStage.details.components && html`
                <div><strong>Extracted Components (${liveBlueprintStage.details.count || liveBlueprintStage.details.components.length}):</strong> ${liveBlueprintStage.details.components.slice(0, 8).join(', ')}${liveBlueprintStage.details.components.length > 8 ? '...' : ''}</div>
              `}
              ${liveBlueprintStage.details.root_part && html`
                <div><strong>Kinematic Root:</strong> ${liveBlueprintStage.details.root_part} · <strong>Assembly Parts:</strong> ${liveBlueprintStage.details.parts_count}</div>
              `}
              ${liveBlueprintStage.details.assembly_name && html`
                <div><strong>Assembly Target:</strong> ${liveBlueprintStage.details.assembly_name} · <strong>Datum:</strong> Z=0</div>
              `}
              ${liveBlueprintStage.details.status === 'verified_viable' && html`
                <div style=${{ color: '#34d399' }}>✓ Spatial Viability Verified: 0 collisions, zero-enclosure verified, ground plane clamped.</div>
              `}
            </div>
          `}
        </div>
      `}

      <div className="spatial-grid-2col">
      <!-- Left Column: Agent Execution Trace & ReAct Stream -->
      <div className="card-glass" style=${{ minHeight: '500px' }}>
        <div className="card-header">
          <div className="card-title-group">
            <div className="card-icon">
              <${Icon} name="brain" size=${16} />
            </div>
            <div>
              <div className="card-title">
                ${reactTrajectory ? 'Live ReAct Trajectory' : (selectedTaskTrace ? `Agent Trace: ${selectedTaskTrace.task_id}` : 'Agent Execution Trace')}
              </div>
              <div className="card-subtitle">
                ${reactTrajectory ? 'Reason · Act · Observe multi-turn loop' : (selectedTaskTrace ? `${selectedTaskTrace.steps?.length || 0} Events · Attempt ${selectedTaskTrace.attempt_count || 1}/${selectedTaskTrace.max_attempts || 3}` : 'Select any task on the right to inspect its full trace')}
              </div>
            </div>
          </div>
          <div style=${{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            ${isExecutingReAct && html`
              <div className="pill running">
                <${Icon} name="activity" size=${12} />
                <span>Multi-Turn Active</span>
              </div>
            `}
            ${selectedTaskTrace && !reactTrajectory && html`
              <span className=${`pill ${selectedTaskTrace.state}`}>${selectedTaskTrace.state}</span>
            `}
          </div>
        </div>

        ${!reactTrajectory && !selectedTaskTrace && !isExecutingReAct && html`
          <div className="empty-state">
            <div className="empty-state-icon">
              <${Icon} name="terminal" size=${36} />
            </div>
            <div className="empty-state-text">
              No task selected. Click on any task in the <strong>Task Lifecycle Feed</strong> on the right to inspect its step-by-step agent trace.
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

        <!-- Mode A: ReAct Trajectory -->
        ${!isExecutingReAct && reactTrajectory && html`
          <div className="trajectory-container">
            <div style=${{ fontSize: '12px', color: '#94a3b8', marginBottom: '8px' }}>
              Goal: <strong style=${{ color: '#fff' }}>${reactTrajectory.goal}</strong>
            </div>

            ${(reactTrajectory.trajectory || []).map((step, idx) => {
              const toolName = typeof step.action === 'string' ? step.action : step.action?.tool;
              const toolParams = step.action_input || step.action?.parameters;

              return html`
                <div key=${idx} className="trajectory-step">
                  <div className=${`step-node-dot ${toolName ? 'action-dot' : ''}`}></div>
                  
                  <div className="turn-header">
                    <span className="turn-pill">Turn ${step.turn || idx + 1}</span>
                    ${toolName && html`
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

                  ${toolName && html`
                    <div className="action-card">
                      <div className="action-header">
                        <span>Motor Action</span>
                        <span className="tool-name-badge">${toolName}</span>
                      </div>
                      ${toolParams && html`
                        <div className="action-params-preview">
                          ${JSON.stringify(toolParams, null, 2)}
                        </div>
                      `}
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
              `;
            })}

            ${reactTrajectory.final_answer && html`
              <div className="final-answer-card">
                <div className="final-header">
                  <${Icon} name="check" size=${16} />
                  <span>Synthesized Solution</span>
                </div>
                <div className="final-content">${reactTrajectory.final_answer}</div>
                ${(reactTrajectory.artifact_path || reactTrajectory.artifact) && (() => {
                  const artName = (reactTrajectory.artifact_path || reactTrajectory.artifact).split(/[/\\]/).pop();
                  return html`
                    <div style=${{ marginTop: '14px', display: 'flex', gap: '8px' }}>
                      <button
                        className="btn btn-secondary"
                        onClick=${() => onOpenViewport(artName)}
                      >
                        <${Icon} name="eye" size=${13} />
                        <span>Inspect Artifact</span>
                      </button>
                      <a
                        className="btn btn-primary"
                        href=${`/workspaces/${artName}`}
                        download
                      >
                        <${Icon} name="download" size=${13} />
                        <span>Download</span>
                      </a>
                    </div>
                  `;
                })()}
              </div>
            `}
          </div>
        `}

        <!-- Mode B: Persisted Selected Task Execution Trace -->
        ${!isExecutingReAct && !reactTrajectory && selectedTaskTrace && html`
          <div className="trajectory-container">
            <div style=${{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px', background: 'rgba(255,255,255,0.03)', padding: '10px 14px', borderRadius: '6px', border: '1px solid rgba(255,255,255,0.06)' }}>
              <div style=${{ fontSize: '12.5px', color: '#cbd5e1', fontWeight: 500, flex: 1, marginRight: '10px' }}>
                <span style=${{ color: '#94a3b8', fontSize: '10.5px', display: 'block', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '2px' }}>Task Goal</span>
                ${selectedTaskTrace.title || selectedTaskTrace.task_id}
              </div>
              ${selectedTaskTrace.artifact_filename && html`
                <button
                  className="btn btn-secondary"
                  style=${{ fontSize: '11px', padding: '5px 12px', display: 'flex', alignItems: 'center', gap: '6px', whiteSpace: 'nowrap' }}
                  onClick=${() => onOpenViewport(selectedTaskTrace.artifact_filename)}
                >
                  <${Icon} name="eye" size=${12} />
                  <span>Preview Artifact</span>
                </button>
              `}
            </div>

            ${(!selectedTaskTrace.steps || selectedTaskTrace.steps.length === 0) && html`
              <div className="empty-state" style=${{ padding: '24px' }}>
                <div className="empty-state-text">No execution steps or tool events recorded for this task.</div>
              </div>
            `}

            ${(selectedTaskTrace.steps || []).map((step, idx) => {
              if (step.type === 'transition') {
                return html`
                  <div key=${idx} className="trajectory-step">
                    <div className="step-node-dot" style=${{ background: step.to_state === 'Succeeded' ? '#10b981' : step.to_state === 'Failed' ? '#ef4444' : '#38bdf8' }}></div>
                    <div className="turn-header">
                      <span className="turn-pill" style=${{ background: 'rgba(255,255,255,0.06)' }}>State Transition</span>
                      <span style=${{ fontSize: '11px', color: '#64748b', fontFamily: 'var(--font-mono)' }}>
                        ${new Date((step.ts || 0) * 1000).toLocaleTimeString()}
                      </span>
                    </div>
                    <div className="card-glass" style=${{ padding: '10px 14px', background: 'rgba(255,255,255,0.02)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '6px' }}>
                      <div style=${{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px' }}>
                        <span className=${`pill ${step.from_state}`} style=${{ fontSize: '10px' }}>${step.from_state}</span>
                        <span style=${{ color: '#64748b' }}>→</span>
                        <span className=${`pill ${step.to_state}`} style=${{ fontSize: '10px' }}>${step.to_state}</span>
                        <span style=${{ color: '#cbd5e1', marginLeft: '6px' }}>${step.reason}</span>
                      </div>
                    </div>
                  </div>
                `;
              } else if (step.type === 'tool_execution') {
                const scriptCode = step.intent?.script_code || (typeof step.intent === 'string' ? step.intent : null);
                return html`
                  <div key=${idx} className="trajectory-step">
                    <div className="step-node-dot action-dot"></div>
                    <div className="turn-header">
                      <span className="turn-pill" style=${{ background: 'rgba(56, 189, 248, 0.15)', color: '#38bdf8' }}>
                        Organ Execution · Attempt #${step.attempt || 1}
                      </span>
                      <span style=${{ fontSize: '11px', color: '#64748b', fontFamily: 'var(--font-mono)' }}>
                        Lease #${step.lease_token || '--'} · ${new Date((step.ts || 0) * 1000).toLocaleTimeString()}
                      </span>
                    </div>

                    <div className="action-card">
                      <div className="action-header">
                        <span style=${{ fontWeight: 600, color: '#f8fafc' }}>Motor Action</span>
                        <span className="tool-name-badge">${step.tool_name}</span>
                        <span className=${`pill ${step.status === 'OUTCOME_RECORDED' ? 'success' : 'failed'}`} style=${{ fontSize: '10px' }}>
                          ${step.status}
                        </span>
                      </div>

                      ${scriptCode ? html`
                        <div style=${{ marginTop: '8px' }}>
                          <div style=${{ fontSize: '11px', color: '#94a3b8', marginBottom: '4px' }}>Executed Script / Code Payload:</div>
                          <pre style=${{ maxHeight: '180px', overflowY: 'auto', background: 'rgba(0,0,0,0.5)', padding: '8px 12px', borderRadius: '4px', fontSize: '11px', fontFamily: 'var(--font-mono)', color: '#38bdf8', whiteSpace: 'pre-wrap' }}>${scriptCode}</pre>
                        </div>
                      ` : html`
                        <div style=${{ marginTop: '6px', fontSize: '11.5px', color: '#cbd5e1' }}>
                          <strong>Intent Parameters:</strong> <code>${JSON.stringify(step.intent)}</code>
                        </div>
                      `}

                      ${step.outcome && html`
                        <div style=${{ marginTop: '8px' }}>
                          <div style=${{ fontSize: '11px', color: '#34d399', fontWeight: 600, marginBottom: '4px' }}>
                            Execution Outcome (${step.outcome?.duration_sec ? `${step.outcome.duration_sec}s` : 'Completed'}):
                          </div>
                          ${step.outcome?.stdout ? html`
                            <pre style=${{ maxHeight: '130px', overflowY: 'auto', background: 'rgba(0,0,0,0.4)', padding: '6px 10px', borderRadius: '4px', fontSize: '10.5px', fontFamily: 'var(--font-mono)', color: '#a7f3d0', whiteSpace: 'pre-wrap' }}>${step.outcome.stdout.trim()}</pre>
                          ` : html`
                            <pre style=${{ maxHeight: '130px', overflowY: 'auto', background: 'rgba(0,0,0,0.4)', padding: '6px 10px', borderRadius: '4px', fontSize: '10.5px', fontFamily: 'var(--font-mono)', color: '#cbd5e1', whiteSpace: 'pre-wrap' }}>${typeof step.outcome === 'object' ? JSON.stringify(step.outcome, null, 2) : String(step.outcome)}</pre>
                          `}
                          ${step.outcome?.stderr && html`
                            <pre style=${{ maxHeight: '100px', overflowY: 'auto', background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.2)', padding: '6px 10px', borderRadius: '4px', fontSize: '10.5px', fontFamily: 'var(--font-mono)', color: '#fca5a5', whiteSpace: 'pre-wrap', marginTop: '4px' }}>${step.outcome.stderr.trim()}</pre>
                          `}
                        </div>
                      `}
                    </div>
                  </div>
                `;
              } else if (step.type === 'mistake') {
                return html`
                  <div key=${idx} className="trajectory-step">
                    <div className="step-node-dot" style=${{ background: '#f43f5e' }}></div>
                    <div className="turn-header">
                      <span className="turn-pill" style=${{ background: 'rgba(244, 63, 94, 0.15)', color: '#f43f5e' }}>
                        Episodic Mistake Recorded
                      </span>
                      <span style=${{ fontSize: '11px', color: '#f43f5e' }}>${step.category}</span>
                    </div>

                    <div style=${{ background: 'rgba(244, 63, 94, 0.08)', border: '1px solid rgba(244, 63, 94, 0.25)', borderRadius: '6px', padding: '10px 14px' }}>
                      <div style=${{ fontSize: '12px', color: '#fca5a5', marginBottom: '4px' }}>
                        <strong>Signature:</strong> ${step.signature}
                      </div>
                      <div style=${{ fontSize: '11.5px', color: '#cbd5e1', fontFamily: 'var(--font-mono)' }}>
                        <strong>Lesson:</strong> ${step.lesson}
                      </div>
                    </div>
                  </div>
                `;
              }
              return null;
            })}
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
              <div className="card-subtitle">State Machine · Monotonic Leases · Verification Gates (${(activeTasks || []).length} tasks)</div>
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
          ${(activeTasks || []).map((task) => {
            const taskId = task.id || task.task_id;
            const taskGoal = task.title || task.goal || task.description || 'Autonomous Task';
            const artifact = task.artifact_filename || task.artifact || null;
            const domain = task.artifact_ext || (artifact ? artifact.split('.').pop() : 'report');
            const attempts = task.attempt_count || task.attempts || 1;
            const maxAttempts = task.max_attempts || 3;
            const isSelected = taskId === selectedTaskId;

            return html`
              <div
                key=${taskId}
                className="card-glass"
                onClick=${() => onSelectTask && onSelectTask(taskId)}
                style=${{
                  padding: '14px',
                  background: isSelected ? 'rgba(56, 189, 248, 0.08)' : 'rgba(255, 255, 255, 0.02)',
                  border: isSelected ? '1px solid #38bdf8' : '1px solid rgba(255, 255, 255, 0.06)',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  boxShadow: isSelected ? '0 0 16px rgba(56, 189, 248, 0.15)' : 'none',
                  transition: 'all 0.2s ease',
                }}
              >
                <div style=${{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
                  <div style=${{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <span style=${{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: isSelected ? '#38bdf8' : '#64748b', fontWeight: isSelected ? 600 : 400 }}>
                      ${taskId}
                    </span>
                    ${isSelected && html`
                      <span style=${{ fontSize: '9px', background: '#38bdf8', color: '#0f172a', padding: '1px 5px', borderRadius: '4px', fontWeight: 700 }}>
                        ACTIVE TRACE
                      </span>
                    `}
                  </div>
                  <div style=${{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <span className=${`pill ${task.state}`}>${task.state}</span>
                    ${['Running', 'Synthesizing', 'Verifying'].includes(task.state) && html`
                      <button
                        className="btn btn-danger"
                        style=${{ padding: '2px 8px', fontSize: '10px' }}
                        onClick=${(e) => { e.stopPropagation(); onCancelTask(taskId); }}
                        title="Cancel Task and Drain Process Tree"
                      >
                        <${Icon} name="square" size=${10} />
                        <span>Cancel</span>
                      </button>
                    `}
                  </div>
                </div>

                <div style=${{ fontSize: '13px', fontWeight: 500, color: '#f8fafc', marginBottom: '8px' }}>
                  ${taskGoal}
                </div>

                <div style=${{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '11px', color: '#94a3b8' }}>
                  <div style=${{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span className=${`domain-badge ${domain}`}>${domain}</span>
                    <span>Attempt: <strong>${attempts}/${maxAttempts}</strong></span>
                  </div>

                  ${artifact && html`
                    <div style=${{ display: 'flex', gap: '6px' }}>
                      <button
                        className="btn btn-secondary"
                        style=${{ padding: '3px 8px', fontSize: '11px' }}
                        onClick=${(e) => { e.stopPropagation(); onOpenViewport(artifact); }}
                      >
                        <${Icon} name="eye" size=${11} />
                        <span>Preview</span>
                      </button>
                      <a
                        className="btn btn-secondary"
                        style=${{ padding: '3px 8px', fontSize: '11px' }}
                        href=${`/workspaces/${artifact}`}
                        download
                        onClick=${(e) => e.stopPropagation()}
                      >
                        <${Icon} name="download" size=${11} />
                      </a>
                    </div>
                  `}
                </div>
              </div>
            `;
          })}
        </div>
      </div>
    </div>
  </div>
  `;
}
