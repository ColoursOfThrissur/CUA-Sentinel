import { React, useState, useEffect } from 'https://esm.sh/react@18.3.1';
import { createRoot } from 'https://esm.sh/react-dom@18.3.1/client';
import htm from 'https://esm.sh/htm@3.1.1';

import { api } from './api.js';
import { TopBar } from './components/TopBar.js';
import { Omnibar } from './components/Omnibar.js';
import { CommandDeck } from './components/CommandDeck.js';
import { DagCanvas } from './components/DagCanvas.js';
import { AgentStudio } from './components/AgentStudio.js';
import { ObservabilityView } from './components/ObservabilityView.js';
import { ViewportModal } from './components/ViewportModal.js';

const html = htm.bind(React.createElement);

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
  const [isDispatching, setIsDispatching] = useState(false);
  const [isExecutingReAct, setIsExecutingReAct] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  // Initial Load
  const loadAll = async () => {
    setRefreshing(true);
    try {
      const [tel, tsk, ags, mods, tpls, runs, msts, sks, tls] = await Promise.allSettled([
        api.getTelemetry(),
        api.getTasks(),
        api.getAgents(),
        api.getModels(),
        api.getDagTemplates(),
        api.getDagRuns(),
        api.getMistakes(),
        api.getSkills(),
        api.getTools(),
      ]);

      if (tel.status === 'fulfilled') setTelemetry(tel.value);
      if (tsk.status === 'fulfilled') setTasks(tsk.value);
      if (ags.status === 'fulfilled') setAgents(ags.value);
      if (mods.status === 'fulfilled' && mods.value && mods.value.length > 0) setModels(mods.value);
      if (tpls.status === 'fulfilled') setDagTemplates(tpls.value);
      if (runs.status === 'fulfilled') {
        setDagRuns(runs.value);
        if (runs.value && runs.value.length > 0 && !selectedDagRun) {
          setSelectedDagRun(runs.value[0]);
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
    const interval = setInterval(async () => {
      try {
        const [tel, tsk] = await Promise.all([api.getTelemetry(), api.getTasks()]);
        setTelemetry(tel);
        setTasks(tsk);
      } catch (e) {}
    }, 3000);
    return () => clearInterval(interval);
  }, []);

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
        // Autonomous DAG Planning
        const planned = await api.planDag({
          goal: prompt,
          model: model,
        });
        // Dispatch the planned steps
        const runRes = await api.dispatchDag({
          steps: planned.steps,
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
  const handleRunTemplate = async (templateName) => {
    setIsDispatching(true);
    try {
      const runRes = await api.dispatchDag({
        template_name: templateName,
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

      <!-- Main Spatial Canvas View Area -->
      <main className="canvas-container">
        ${activeTab === 'command' && html`
          <${CommandDeck}
            reactTrajectory=${reactTrajectory}
            activeTasks=${tasks}
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
            onSelectRun=${setSelectedDagRun}
            onRunTemplate=${handleRunTemplate}
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
