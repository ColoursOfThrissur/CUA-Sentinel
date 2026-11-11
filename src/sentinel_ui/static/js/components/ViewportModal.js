import { React, useState, useEffect, useRef } from 'https://esm.sh/react@18.3.1';
import htm from 'https://esm.sh/htm@3.1.1';
import { Icon } from '../icons.js';
import { api } from '../api.js';

const html = htm.bind(React.createElement);

export function ViewportModal({ artifactName, onClose }) {
  const [content, setContent] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [copied, setCopied] = useState(false);
  const [csvFilter, setCsvFilter] = useState('');
  const [isWireframe, setIsWireframe] = useState(false);

  const canvasRef = useRef(null);
  const threeCleanupRef = useRef(null);

  const fileType = artifactName ? artifactName.split('.').pop().toLowerCase() : '';
  const fileUrl = `/workspaces/${artifactName}`;

  useEffect(() => {
    if (!artifactName) return;
    setLoading(true);
    setError(null);

    if (fileType === 'obj') {
      setLoading(false);
      initThreeJS(fileUrl);
    } else {
      api.fetchArtifact(fileUrl)
        .then((text) => {
          setContent(text);
          setLoading(false);
        })
        .catch((err) => {
          setError(err.message || 'Failed to load artifact content');
          setLoading(false);
        });
    }

    return () => {
      if (threeCleanupRef.current) threeCleanupRef.current();
    };
  }, [artifactName]);

  const initThreeJS = async (url) => {
    try {
      const THREE = await import('https://esm.sh/three@0.160.0');
      const { OBJLoader } = await import('https://esm.sh/three@0.160.0/examples/jsm/loaders/OBJLoader.js');
      const { OrbitControls } = await import('https://esm.sh/three@0.160.0/examples/jsm/controls/OrbitControls.js');

      if (!canvasRef.current) return;

      const container = canvasRef.current;
      const width = container.clientWidth;
      const height = container.clientHeight;

      const scene = new THREE.Scene();
      scene.background = new THREE.Color(0x0a0e17);

      const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 1000);
      camera.position.set(0, 3, 7);

      const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
      renderer.setSize(width, height);
      renderer.setPixelRatio(window.devicePixelRatio);
      container.innerHTML = '';
      container.appendChild(renderer.domElement);

      const controls = new OrbitControls(camera, renderer.domElement);
      controls.enableDamping = true;
      controls.dampingFactor = 0.05;

      const ambientLight = new THREE.AmbientLight(0xffffff, 0.8);
      scene.add(ambientLight);

      const dirLight1 = new THREE.DirectionalLight(0x38bdf8, 1.2);
      dirLight1.position.set(5, 10, 7);
      scene.add(dirLight1);

      const dirLight2 = new THREE.DirectionalLight(0xa855f7, 0.8);
      dirLight2.position.set(-5, -5, -5);
      scene.add(dirLight2);

      const grid = new THREE.GridHelper(10, 20, 0x1e293b, 0x0f172a);
      grid.position.y = -1;
      scene.add(grid);

      let currentMesh = null;
      const loader = new OBJLoader();
      loader.load(url, (obj) => {
        currentMesh = obj;
        const box = new THREE.Box3().setFromObject(obj);
        const center = box.getCenter(new THREE.Vector3());
        const size = box.getSize(new THREE.Vector3());

        const maxDim = Math.max(size.x, size.y, size.z);
        const scale = 3.5 / (maxDim || 1);
        obj.scale.set(scale, scale, scale);

        obj.position.x -= center.x * scale;
        obj.position.y -= center.y * scale;
        obj.position.z -= center.z * scale;

        obj.traverse((child) => {
          if (child.isMesh) {
            child.material = new THREE.MeshStandardMaterial({
              color: 0x93c5fd,
              metalness: 0.2,
              roughness: 0.4,
              wireframe: isWireframe,
            });
          }
        });

        scene.add(obj);
      });

      let animationFrameId;
      const animate = () => {
        animationFrameId = requestAnimationFrame(animate);
        if (currentMesh) {
          currentMesh.rotation.y += 0.003;
        }
        controls.update();
        renderer.render(scene, camera);
      };
      animate();

      threeCleanupRef.current = () => {
        cancelAnimationFrame(animationFrameId);
        renderer.dispose();
      };
    } catch (e) {
      console.error('Three.js failed to initialize', e);
      setError('Three.js 3D viewport initialization failed: ' + e.message);
    }
  };

  const copyToClipboard = () => {
    navigator.clipboard.writeText(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const parseCSV = (csvText) => {
    const lines = csvText.trim().split('\n');
    if (lines.length === 0) return { headers: [], rows: [] };
    const headers = lines[0].split(',').map((h) => h.trim().replace(/^"|"$/g, ''));
    const rows = lines.slice(1).map((line) =>
      line.split(',').map((col) => col.trim().replace(/^"|"$/g, ''))
    );
    return { headers, rows };
  };

  return html`
    <div className="modal-overlay" onClick=${onClose}>
      <div className="modal-content" onClick=${(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div style=${{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <${Icon}
              name=${fileType === 'obj' ? 'box' : fileType === 'csv' ? 'activity' : fileType === 'py' ? 'code' : 'fileText'}
              size=${18}
            />
            <span style=${{ fontSize: '15px', fontWeight: 600, color: '#fff' }}>${artifactName}</span>
            <span className="pill pending">${fileType.toUpperCase()}</span>
          </div>

          <div style=${{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <a className="btn btn-secondary" href=${fileUrl} download title="Download raw artifact">
              <${Icon} name="download" size=${13} />
              <span>Download</span>
            </a>
            <button className="btn-icon" onClick=${onClose}>
              <${Icon} name="close" size=${16} />
            </button>
          </div>
        </div>

        <div className="modal-body" style=${{ padding: '16px' }}>
          ${loading && html`
            <div className="empty-state">
              <div className="empty-state-icon" style=${{ animation: 'spin 1.5s infinite linear' }}>
                <${Icon} name="refresh" size=${32} />
              </div>
              <div className="empty-state-text">Loading artifact viewport...</div>
            </div>
          `}

          ${error && html`
            <div className="empty-state">
              <div className="empty-state-text" style=${{ color: '#f43f5e' }}>${error}</div>
            </div>
          `}

          <!-- 3D OBJ Viewport -->
          ${fileType === 'obj' && html`
            <div className="viewport-3d-container">
              <div ref=${canvasRef} className="viewport-3d-canvas"></div>
              <div className="viewport-3d-hint">Left click to orbit · Scroll to zoom · Right click to pan</div>
            </div>
          `}

          <!-- CSV Table Viewport -->
          ${fileType === 'csv' && !loading && !error && (() => {
            const { headers, rows } = parseCSV(content);
            const filteredRows = rows.filter((r) =>
              r.some((c) => c.toLowerCase().includes(csvFilter.toLowerCase()))
            );

            return html`
              <div className="csv-viewport-container">
                <div className="csv-toolbar">
                  <span style=${{ fontSize: '12px', color: '#94a3b8' }}>
                    Total: <strong>${rows.length}</strong> rows · Filtered: <strong>${filteredRows.length}</strong>
                  </span>
                  <input
                    type="text"
                    className="csv-search-input"
                    placeholder="Search table rows..."
                    value=${csvFilter}
                    onChange=${(e) => setCsvFilter(e.target.value)}
                  />
                </div>

                <div className="csv-table-wrapper">
                  <table className="csv-spatial-table">
                    <thead>
                      <tr>
                        ${headers.map((h, i) => html`<th key=${i}>${h}</th>`)}
                      </tr>
                    </thead>
                    <tbody>
                      ${filteredRows.map((row, ri) => html`
                        <tr key=${ri}>
                          ${row.map((col, ci) => html`<td key=${ci}>${col}</td>`)}
                        </tr>
                      `)}
                    </tbody>
                  </table>
                </div>
              </div>
            `;
          })()}

          <!-- Python & Code Viewport -->
          ${(fileType === 'py' || fileType === 'json') && !loading && !error && html`
            <div className="code-viewport-container">
              <div className="code-toolbar">
                <span>${fileType.toUpperCase()} Source</span>
                <button
                  className="btn btn-secondary"
                  style=${{ padding: '3px 8px', fontSize: '11px' }}
                  onClick=${copyToClipboard}
                >
                  ${copied ? 'Copied!' : 'Copy Code'}
                </button>
              </div>
              <pre className="code-pre"><code>${content}</code></pre>
            </div>
          `}

          <!-- Markdown Viewport -->
          ${(fileType === 'md' || fileType === 'txt') && !loading && !error && html`
            <div className="markdown-viewport-container">
              <pre style=${{ whiteSpace: 'pre-wrap', fontFamily: 'inherit', margin: 0 }}>${content}</pre>
            </div>
          `}
        </div>
      </div>
    </div>
  `;
}
