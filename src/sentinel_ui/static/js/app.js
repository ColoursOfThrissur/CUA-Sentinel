import { useState, useEffect } from 'https://esm.sh/react@18.3.1';
import { createRoot } from 'https://esm.sh/react-dom@18.3.1/client';
import { html } from './html.js';

import { api } from './api.js';
import { TopBar } from './components/TopBar.js';
import { Omnibar } from './components/Omnibar.js';
import { CommandDeck } from './components/CommandDeck.js';
import { DagCanvas } from './components/DagCanvas.js';
import { AgentStudio } from './components/AgentStudio.js';
import { ObservabilityView } from './components/ObservabilityView.js';
import { GymConsole } from './components/GymConsole.js';
import { ViewportModal } from './components/ViewportModal.js';

export function App() {
  const [activeTab, setActiveTab] = useState('command'); // 'command' | 'dag' | 'agents' | 'observability'
  const [telemetry, setTelemetry] = useState(null);
  const [tasks, setTasks] = useState([]);
  const [models, setModels] = useState(['qwen3.5:9b', 'qwen3:14b', 'phi3:mini']);
  const [agents, setAgents] = useState([]);
  const [dagTemplates, setDagTemplates] = useState([]);
  const [dagRuns, setDagRuns] = useState([]);
  const [selectedDagRun, setSelectedDagRun] = useState(null);
  const [mistakes, setMistakes] = useState([]);
  const [skills, setSkills] = useState([]);
  const [tools, setTools] = useState([]);

  const [reactTrajectory, setReactTrajectory] = useState(null);
  const [activeViewportArtifact, setActiveViewportArtifact] = useState(null);
  const [pendingApprovals, setPendingApprovals] = useState([]);
  const [isDispatching, setIsDispatching] = useState(false);
  const [isExecutingReAct, setIsExecutingReAct] = useState(false);
  const [liveBlueprintStage, setLiveBlueprintStage] = useState(null);
  const [selectedTaskId, setSelectedTaskId] = useState(null);
  const [selectedTaskTrace, setSelectedTaskTrace] = useState(null);
  const [refreshing, setRefreshing] = useState(false);

  // Initial Load
  const loadAll = async () => {
    setRefreshing(true);
    try {
      const [tel, tsk, ags, mods, tpls, runs, msts, sks, tls, apprs] = await Promise.allSettled([
        api.getTelemetry(),
        api.getTasks(),
        api.getAgents(),
        api.getModels(),
        api.getDagTemplates(),
        api.getDagRuns(),
        api.getMistakes(),
        api.getSkills(),
        api.getTools(),
        api.getApprovals(),
      ]);

      if (tel.status === 'fulfilled') setTelemetry(tel.value);
      if (tsk.status === 'fulfilled') {
        setTasks(tsk.value);
        if (tsk.value && tsk.value.length > 0 && !selectedTaskId) {
          const firstId = tsk.value[0].id;
          setSelectedTaskId(firstId);
          api.getTaskTrace(firstId).then((tr) => setSelectedTaskTrace(tr)).catch(() => {});
        }
      }
      if (ags.status === 'fulfilled') setAgents(ags.value);
      if (mods.status === 'fulfilled' && mods.value && mods.value.length > 0) setModels(mods.value);
      if (tpls.status === 'fulfilled') setDagTemplates(tpls.value);
      if (apprs.status === 'fulfilled' && Array.isArray(apprs.value)) setPendingApprovals(apprs.value);
      if (runs.status === 'fulfilled') {
        setDagRuns(runs.value);
        if (runs.value && runs.value.length > 0 && !selectedDagRun) {
          // Fetch full DAG details including step nodes
          api.getDagStatus(runs.value[0].id)
            .then((fullRun) => setSelectedDagRun(fullRun))
            .catch(() => setSelectedDagRun(runs.value[0]));
        }
      }
      if (msts.status === 'fulfilled') setMistakes(msts.value);
      if (sks.status === 'fulfilled') setSkills(sks.value);
      if (tls.status === 'fulfilled') setTools(tls.value);
    } catch (e) {
      console.error('Error refreshing Sentinel data', e);
    } finally {
      setRefreshing(false);
    }
  };

  useEffect(() => {
    loadAll();

    // Real-Time Telemetry & Event Streaming (Pillar 1)
    const es = api.subscribeEvents((event) => {
      if (event.type === 'hitl_requested') {
        api.getApprovals().then((apprs) => setPendingApprovals(apprs)).catch(() => {});
      } else if (event.type === 'hitl_resolved') {
        const resolvedId = event.data?.approval_id;
        if (resolvedId) {
          setPendingApprovals((prev) => prev.filter((a) => a.approval_id !== resolvedId));
        }
      } else if (event.type === 'task_state') {
        api.getTasks().then((t) => setTasks(t)).catch(() => {});
      } else if (event.type === 'blueprint_stage') {
        setLiveBlueprintStage(event.data);
      }
    });

    const interval = setInterval(async () => {
      try {
        const [tel, tsk, apprs] = await Promise.all([
          api.getTelemetry(),
          api.getTasks(),
          api.getApprovals(),
        ]);
        setTelemetry(tel);
        setTasks(tsk);
        if (Array.isArray(apprs)) setPendingApprovals(apprs);
        if (selectedDagRun && (selectedDagRun.state === 'Running' || selectedDagRun.state === 'Pending')) {
          const updatedDag = await api.getDagStatus(selectedDagRun.id);
          setSelectedDagRun(updatedDag);
        }
      } catch (e) {}
    }, 2500);

    return () => {
      clearInterval(interval);
      if (es) es.close();
    };
  }, [selectedDagRun]);

  // HITL Checkpoint Handlers (Pillar 2)
  const handleApprove = async (approvalId) => {
    try {
      await api.approveAction(approvalId);
      setPendingApprovals((prev) => prev.filter((a) => a.approval_id !== approvalId));
      loadAll();
    } catch (e) {
      alert('Error approving action: ' + e.message);
    }
  };

  const handleDeny = async (approvalId) => {
    try {
      await api.denyAction(approvalId);
      setPendingApprovals((prev) => prev.filter((a) => a.approval_id !== approvalId));
      loadAll();
    } catch (e) {
      alert('Error denying action: ' + e.message);
    }
  };

  // Select DAG Run & fetch full steps
  const handleSelectRun = async (run) => {
    try {
      const fullRun = await api.getDagStatus(run.id);
      setSelectedDagRun(fullRun);
    } catch (e) {
      setSelectedDagRun(run);
    }
  };

  // Dispatch Action from Omnibar
  const handleDispatch = async ({ mode, prompt, model, agentId }) => {
    setIsDispatching(true);

    if (mode === 'react') {
      setIsExecutingReAct(true);
      setActiveTab('command');
      setReactTrajectory(null);
      try {
        const res = await api.executeReAct({
          goal: prompt,
          model: model,
          max_turns: 5,
        });
        setReactTrajectory(res);
      } catch (err) {
        alert('ReAct Execution Failed: ' + err.message);
      } finally {
        setIsExecutingReAct(false);
        setIsDispatching(false);
        loadAll();
      }
    } else if (mode === 'synthesize') {
      try {
        await api.dispatchTask({
          goal: prompt,
          agent_id: agentId,
          model: model,
        });
        setActiveTab('command');
        await loadAll();
      } catch (err) {
        alert('Synthesis Dispatch Failed: ' + err.message);
      } finally {
        setIsDispatching(false);
      }
    } else if (mode === 'dag') {
      try {
        setActiveTab('dag');
        // Dispatch autonomous goal or planner
        const runRes = await api.dispatchDag({
          goal: prompt,
          model: model,
        });
        setSelectedDagRun(runRes);
        await loadAll();
      } catch (err) {
        alert('DAG Pipeline Dispatch Failed: ' + err.message);
      } finally {
        setIsDispatching(false);
      }
    }
  };

  // Run a Pre-built DAG Template
  const handleRunTemplate = async (templateId) => {
    setIsDispatching(true);
    try {
      const runRes = await api.dispatchDag({
        template: templateId,
      });
      setSelectedDagRun(runRes);
      setActiveTab('dag');
      await loadAll();
    } catch (err) {
      alert('Template Dispatch Failed: ' + err.message);
    } finally {
      setIsDispatching(false);
    }
  };

  // Launch a Custom Composed Multi-Agent Pipeline
  const handleDispatchCustomPipeline = async ({ name, description, steps }) => {
    setIsDispatching(true);
    try {
      const runRes = await api.dispatchDag({
        name,
        description,
        steps,
      });
      setSelectedDagRun(runRes);
      setActiveTab('dag');
      await loadAll();
    } catch (err) {
      alert('Custom Pipeline Dispatch Failed: ' + err.message);
    } finally {
      setIsDispatching(false);
    }
  };

  // Cancel Running Task
  const handleCancelTask = async (taskId) => {
    try {
      await api.cancelTask(taskId);
      await loadAll();
    } catch (err) {
      alert('Failed to cancel task: ' + err.message);
    }
  };

  // Cancel Running DAG
  const handleCancelDag = async (dagId) => {
    try {
      await api.cancelDag(dagId);
      await loadAll();
    } catch (err) {
      alert('Failed to cancel DAG: ' + err.message);
    }
  };

  // Publish New Agent
  const handlePublishAgent = async (manifest) => {
    try {
      await api.publishAgent(manifest);
      await loadAll();
    } catch (err) {
      alert('Failed to publish agent: ' + err.message);
    }
  };

  const handleSelectTask = async (taskId) => {
    setSelectedTaskId(taskId);
    try {
      const trace = await api.getTaskTrace(taskId);
      setSelectedTaskTrace(trace);
    } catch (err) {
      console.error('Failed to load task trace:', err);
    }
  };

  return html`
    <div>
      <!-- Floating Top Navigation & Telemetry -->
      <${TopBar}
        activeTab=${activeTab}
        onTabChange=${setActiveTab}
        telemetry=${telemetry}
        onRefresh=${loadAll}
        refreshing=${refreshing}
      />

      <!-- Human-in-the-Loop (HITL) Checkpoint Banner -->
      ${pendingApprovals.length > 0 && html`
        <div style=${{
          margin: '0.75rem 1.5rem',
          padding: '1rem',
          background: 'rgba(239, 68, 68, 0.12)',
          border: '1px solid var(--accent-danger, #ef4444)',
          borderRadius: '8px',
          display: 'flex',
          flexDirection: 'column',
          gap: '0.75rem',
          zIndex: 100,
        }}>
          <div style=${{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style=${{ fontWeight: 'bold', color: 'var(--accent-danger, #ef4444)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              ⚠️ Human-in-the-Loop Checkpoint: Irreversible Tool Clearance Required
            </span>
            <span style=${{ fontSize: '0.75rem', opacity: 0.8 }}>
              ${pendingApprovals.length} Action(s) Paused
            </span>
          </div>

          ${pendingApprovals.map((appr) => html`
            <div key=${appr.approval_id} style=${{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              background: 'rgba(0, 0, 0, 0.25)',
              padding: '0.75rem 1rem',
              borderRadius: '6px',
            }}>
              <div style=${{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                <span style=${{ fontSize: '0.9rem', fontWeight: 600 }}>
                  Tool: <code style=${{ color: 'var(--accent-primary, #3b82f6)' }}>${appr.tool_name}</code>
                  <span style=${{ opacity: 0.6, marginLeft: '0.75rem' }}>Task: ${appr.task_id}</span>
                </span>
                <span style=${{ fontSize: '0.8rem', opacity: 0.8 }}>
                  ${appr.reason || 'Explicit operator approval required for execution'}
                </span>
                ${appr.params && Object.keys(appr.params).length > 0 && html`
                  <span style=${{ fontSize: '0.75rem', opacity: 0.6, fontFamily: 'monospace' }}>
                    Params: ${JSON.stringify(appr.params)}
                  </span>
                `}
              </div>

              <div style=${{ display: 'flex', gap: '0.5rem' }}>
                <button
                  onClick=${() => handleApprove(appr.approval_id)}
                  style=${{
                    background: 'var(--accent-success, #10b981)',
                    color: '#fff',
                    border: 'none',
                    padding: '0.4rem 0.8rem',
                    borderRadius: '4px',
                    fontWeight: 600,
                    cursor: 'pointer',
                  }}
                >
                  Approve Execution
                </button>
                <button
                  onClick=${() => handleDeny(appr.approval_id)}
                  style=${{
                    background: 'rgba(239, 68, 68, 0.2)',
                    color: 'var(--accent-danger, #ef4444)',
                    border: '1px solid var(--accent-danger, #ef4444)',
                    padding: '0.4rem 0.8rem',
                    borderRadius: '4px',
                    fontWeight: 600,
                    cursor: 'pointer',
                  }}
                >
                  Deny
                </button>
              </div>
            </div>
          `)}
        </div>
      `}

      <!-- Main Spatial Canvas View Area -->
      <main className="canvas-container">
        ${activeTab === 'command' && html`
          <${CommandDeck}
            reactTrajectory=${reactTrajectory}
            activeTasks=${tasks}
            selectedTaskId=${selectedTaskId}
            selectedTaskTrace=${selectedTaskTrace}
            onSelectTask=${handleSelectTask}
            liveBlueprintStage=${liveBlueprintStage}
            onCancelTask=${handleCancelTask}
            onOpenViewport=${setActiveViewportArtifact}
            isExecutingReAct=${isExecutingReAct}
          />
        `}

        ${activeTab === 'dag' && html`
          <${DagCanvas}
            templates=${dagTemplates}
            activeRuns=${dagRuns}
            selectedRun=${selectedDagRun}
            onSelectRun=${handleSelectRun}
            onRunTemplate=${handleRunTemplate}
            onDispatchCustomPipeline=${handleDispatchCustomPipeline}
            onCancelDag=${handleCancelDag}
            onOpenViewport=${setActiveViewportArtifact}
            isDispatching=${isDispatching}
          />
        `}

        ${activeTab === 'agents' && html`
          <${AgentStudio}
            agents=${agents}
            onPublishAgent=${handlePublishAgent}
          />
        `}

        ${activeTab === 'observability' && html`
          <${ObservabilityView}
            telemetry=${telemetry}
            mistakes=${mistakes}
            skills=${skills}
            tools=${tools}
          />
        `}

        ${activeTab === 'gym' && html`
          <${GymConsole}
            liveBlueprintStage=${liveBlueprintStage}
            onOpenViewport=${setActiveViewportArtifact}
          />
        `}
      </main>

      <!-- Floating Command Console Omnibar -->
      <${Omnibar}
        models=${models}
        agents=${agents}
        onDispatch=${handleDispatch}
        isDispatching=${isDispatching || isExecutingReAct}
      />

      <!-- Interactive Viewport Modal (3D, CSV, Code, MD) -->
      ${activeViewportArtifact && html`
        <${ViewportModal}
          artifactName=${activeViewportArtifact}
          onClose=${() => setActiveViewportArtifact(null)}
        />
      `}
    </div>
  `;
}

// Mount React Root
const rootElement = document.getElementById('root');
if (rootElement) {
  createRoot(rootElement).render(html`<${App} />`);
}
