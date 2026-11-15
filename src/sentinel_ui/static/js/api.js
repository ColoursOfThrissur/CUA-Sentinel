/**
 * Sentinel REST API Client
 */

const BASE_URL = window.location.origin;

async function request(endpoint, options = {}) {
  const url = `${BASE_URL}${endpoint}`;
  const headers = {
    'Content-Type': 'application/json',
    ...(options.headers || {}),
  };

  try {
    const res = await fetch(url, { ...options, headers });
    if (!res.ok) {
      let errDetail = `${res.status} ${res.statusText}`;
      try {
        const body = await res.json();
        if (body.detail) errDetail = body.detail;
      } catch (e) {}
      throw new Error(errDetail);
    }
    const contentType = res.headers.get('content-type') || '';
    if (contentType.includes('application/json')) {
      return await res.json();
    }
    return await res.text();
  } catch (err) {
    console.error(`API Error [${endpoint}]:`, err);
    throw err;
  }
}

export const api = {
  // Telemetry & Hardware
  getTelemetry: () => request('/api/telemetry'),
  getConfig: () => request('/api/config'),
  getModels: async () => {
    const data = await request('/api/models');
    if (Array.isArray(data)) return data;
    const active = data?.active_model;
    const list = data?.available_models || [];
    if (active && list.includes(active)) {
      return [active, ...list.filter((m) => m !== active)];
    }
    return active ? [active, ...list] : list;
  },

  // Tasks & Dispatch
  getTasks: () => request('/api/tasks'),
  getTaskTrace: (taskId) => request(`/api/tasks/${taskId}/trace`),
  dispatchTask: (data) => request('/api/tasks/dispatch', { method: 'POST', body: JSON.stringify(data) }),
  cancelTask: (taskId) => request(`/api/tasks/${taskId}/cancel`, { method: 'POST' }),

  // Multi-Turn ReAct Execution
  executeReAct: (data) => request('/api/agent/react', { method: 'POST', body: JSON.stringify(data) }),

  // Multi-Agent DAG Pipelines
  getDagTemplates: () => request('/api/dag/templates'),
  getDagRuns: () => request('/api/dag/runs'),
  getDagStatus: (dagId) => request(`/api/dag/${dagId}`),
  planDag: (data) => request('/api/dag/plan', { method: 'POST', body: JSON.stringify(data) }),
  dispatchDag: (data) => request('/api/dag/dispatch', { method: 'POST', body: JSON.stringify(data) }),
  cancelDag: (dagId) => request(`/api/dag/${dagId}/cancel`, { method: 'POST' }),

  // Gate A Agents
  getAgents: () => request('/api/agents'),
  publishAgent: (data) => request('/api/agents/publish', { method: 'POST', body: JSON.stringify(data) }),
  draftAgent: (data) => request('/api/agents/draft', { method: 'POST', body: JSON.stringify(data) }),

  // Mistake Ledger, Skills, Organs
  getMistakes: () => request('/api/mistakes'),
  getSkills: () => request('/api/skills'),
  executeSkill: (data) => request('/api/skills/execute', { method: 'POST', body: JSON.stringify(data) }),
  getTools: () => request('/api/tools'),
  getSideEffects: () => request('/api/side_effects'),

  // Artifact Content Fetch
  fetchArtifact: (url) => fetch(url).then(r => r.text()),

  // Human-in-the-Loop (HITL) Checkpoints
  getApprovals: () => request('/api/approvals'),
  approveAction: (approvalId) => request(`/api/approvals/${approvalId}/approve`, { method: 'POST' }),
  denyAction: (approvalId) => request(`/api/approvals/${approvalId}/deny`, { method: 'POST' }),

  // Real-Time Server-Sent Events (SSE) Stream
  subscribeEvents: (onEvent, taskId = null) => {
    const url = taskId ? `${BASE_URL}/api/tasks/${taskId}/events` : `${BASE_URL}/api/events`;
    const es = new EventSource(url);
    es.onmessage = (e) => {
      try {
        const payload = JSON.parse(e.data);
        if (onEvent) onEvent(payload);
      } catch (err) {
        console.debug('SSE parse error:', err);
      }
    };
    es.onerror = (err) => {
      console.debug('SSE connection state:', es.readyState);
    };
    return es;
  },

  // Gymnasium & Autonomous Self-Evolution Engine
  getGymStatus: () => request('/api/gym/status'),
  startGym: (data = { max_hours: 5.0, domain: '3d' }) => request('/api/gym/start', { method: 'POST', body: JSON.stringify(data) }),
  stopGym: () => request('/api/gym/stop', { method: 'POST' }),

  // Storage & Observability Retention
  getStorageStats: () => request('/api/observability/storage'),
  pruneStorage: (options = {}) => request('/api/observability/prune', { method: 'POST', body: JSON.stringify(options) }),
};
