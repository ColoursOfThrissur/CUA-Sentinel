import { useState, useEffect, useRef } from 'https://esm.sh/react@18.3.1';
import { html } from '../html.js';
import { Icon } from '../icons.js';
import { api } from '../api.js';

export function ViewportModal({ artifactName, onClose }) {
  const [content, setContent] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [copied, setCopied] = useState(false);
  const [csvFilter, setCsvFilter] = useState('');
  const [isWireframe, setIsWireframe] = useState(false);
  const [autoRotate, setAutoRotate] = useState(true);
  const [viewMode, setViewMode] = useState('formatted'); // 'formatted' | 'raw'
  const [meshStats, setMeshStats] = useState({ vertices: 0, faces: 0, dimensions: '' });
  const [fileSizeBytes, setFileSizeBytes] = useState(0);

  // Material & Modifier Panel state
  const [showMatPanel, setShowMatPanel] = useState(false);
  const [matHexColor, setMatHexColor] = useState('#7ec8e3');
  const [matMetalness, setMatMetalness] = useState(0.1);
  const [matRoughness, setMatRoughness] = useState(0.4);
  const [matEmission, setMatEmission] = useState(0.0);
  const [modifierType, setModifierType] = useState('subdivision');
  const [modifierStrength, setModifierStrength] = useState(1.0);
  const [matObjName, setMatObjName] = useState('');
  const [sceneObjects, setSceneObjects] = useState([]);
  const [matOpBusy, setMatOpBusy] = useState(false);
  const [matOpResult, setMatOpResult] = useState(null);
  const [matOpError, setMatOpError] = useState(null);
  const [workspacePath, setWorkspacePath] = useState('');
  const [imageDims, setImageDims] = useState({ width: 0, height: 0 });
  const [imageZoom, setImageZoom] = useState(1);
  const [isExploded, setIsExploded] = useState(false);
  const [explodeFactor, setExplodeFactor] = useState(1.0);

  const canvasRef = useRef(null);
  const threeCleanupRef = useRef(null);
  const cameraRef = useRef(null);
  const controlsRef = useRef(null);
  const meshRef = useRef(null);
  const autoRotateRef = useRef(true);

  const cleanName = artifactName ? artifactName.split(/[/\\]/).pop() : '';
  const fileType = cleanName ? cleanName.split('.').pop().toLowerCase() : '';
  const isImage = ['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp', 'svg'].includes(fileType);
  const fileUrl = `/workspaces/${cleanName}`;

  // Fetch dynamic workspace path from backend once
  useEffect(() => {
    fetch('/api/workspace/path')
      .then((r) => r.json())
      .then((data) => {
        if (data.workspace_dir) setWorkspacePath(data.workspace_dir);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!cleanName) return;
    setLoading(true);
    setError(null);
    setContent('');
    setMeshStats({ vertices: 0, faces: 0, dimensions: '' });
    setImageDims({ width: 0, height: 0 });
    setImageZoom(1);

    if (fileType === 'obj') {
      // 3D Model: fetch text to calculate size/lines and initialize ThreeJS
      fetch(fileUrl)
        .then((res) => {
          if (!res.ok) throw new Error(`HTTP ${res.status}: Artifact '${cleanName}' not found on server`);
          const cl = res.headers.get('content-length');
          if (cl) setFileSizeBytes(parseInt(cl, 10));
          return res.text();
        })
        .then((text) => {
          setContent(text);
          setFileSizeBytes(text.length);
          setLoading(false);
          startThreeJS(fileUrl);
        })
        .catch((err) => {
          setError(err.message || 'Failed to load 3D artifact');
          setLoading(false);
        });
    } else if (isImage) {
      // Image Artifact (Desktop screenshots, visual sensory captures)
      const img = new Image();
      img.onload = () => {
        setImageDims({ width: img.naturalWidth, height: img.naturalHeight });
        setLoading(false);
      };
      img.onerror = () => {
        setError(`Failed to load image artifact '${cleanName}'`);
        setLoading(false);
      };
      img.src = fileUrl;

      fetch(fileUrl, { method: 'HEAD' })
        .then((res) => {
          const cl = res.headers.get('content-length');
          if (cl) setFileSizeBytes(parseInt(cl, 10));
        })
        .catch(() => {});
    } else {
      // CSV, Python, Markdown, Text
      fetch(fileUrl)
        .then((res) => {
          if (!res.ok) throw new Error(`HTTP ${res.status}: Artifact '${cleanName}' not found on server`);
          const cl = res.headers.get('content-length');
          if (cl) setFileSizeBytes(parseInt(cl, 10));
          return res.text();
        })
        .then((text) => {
          setContent(text);
          setFileSizeBytes(text.length);
          setLoading(false);
        })
        .catch((err) => {
          setError(err.message || 'Failed to load artifact content');
          setLoading(false);
        });
    }

    return () => {
      if (threeCleanupRef.current) {
        threeCleanupRef.current();
        threeCleanupRef.current = null;
      }
    };
  }, [cleanName]);

  // Robust Three.js initialization with mount-wait loop
  const startThreeJS = (url) => {
    let attempts = 0;
    const tryInit = () => {
      attempts++;
      if (canvasRef.current && canvasRef.current.clientWidth > 0) {
        initThreeJS(canvasRef.current, url);
      } else if (attempts < 20) {
        requestAnimationFrame(tryInit);
      }
    };
    requestAnimationFrame(tryInit);
  };

  const initThreeJS = async (container, url) => {
    try {
      if (threeCleanupRef.current) threeCleanupRef.current();

      const THREE = await import('https://esm.sh/three@0.160.0');
      const { OBJLoader } = await import('https://esm.sh/three@0.160.0/examples/jsm/loaders/OBJLoader.js');
      const { MTLLoader } = await import('https://esm.sh/three@0.160.0/examples/jsm/loaders/MTLLoader.js');
      const { OrbitControls } = await import('https://esm.sh/three@0.160.0/examples/jsm/controls/OrbitControls.js');

      const width = container.clientWidth || 800;
      const height = container.clientHeight || 520;

      const scene = new THREE.Scene();
      scene.background = new THREE.Color(0x0a0e17);

      const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 1000);
      camera.position.set(0, 3, 7);
      cameraRef.current = camera;

      const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
      renderer.setSize(width, height);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      container.innerHTML = '';
      container.appendChild(renderer.domElement);

      const controls = new OrbitControls(camera, renderer.domElement);
      controls.enableDamping = true;
      controls.dampingFactor = 0.05;
      controlsRef.current = controls;

      const ambientLight = new THREE.AmbientLight(0xffffff, 0.9);
      scene.add(ambientLight);

      const dirLight1 = new THREE.DirectionalLight(0x38bdf8, 1.4);
      dirLight1.position.set(5, 10, 7);
      scene.add(dirLight1);

      const dirLight2 = new THREE.DirectionalLight(0xa855f7, 0.9);
      dirLight2.position.set(-5, -5, -5);
      scene.add(dirLight2);

      const grid = new THREE.GridHelper(10, 20, 0x1e293b, 0x0f172a);
      grid.position.y = -1;
      scene.add(grid);

      let currentMesh = null;

      const setupLoadedObject = (obj) => {
        currentMesh = obj;
        meshRef.current = obj;

        let vCount = 0;
        let fCount = 0;

        obj.traverse((child) => {
          if (child.isMesh && child.geometry) {
            const g = child.geometry;
            if (g.attributes.position) {
              vCount += g.attributes.position.count;
            }
            if (g.index) {
              fCount += g.index.count / 3;
            } else if (g.attributes.position) {
              fCount += g.attributes.position.count / 3;
            }

            // Tag object name for targeted material editing
            child.userData.objectName = child.name || child.parent?.name || '';

            // Ensure every mesh has its OWN isolated cloned material instance
            if (child.material) {
              if (Array.isArray(child.material)) {
                child.material = child.material.map((m) => {
                  const cl = m.clone();
                  cl.wireframe = isWireframe;
                  return cl;
                });
              } else {
                child.material = child.material.clone();
                child.material.wireframe = isWireframe;
              }
            } else {
              child.material = new THREE.MeshStandardMaterial({
                color: 0x93c5fd,
                metalness: 0.3,
                roughness: 0.35,
                wireframe: isWireframe,
              });
            }
          }
        });

        // Compute Bounding Box, Dimensions & Normalize Scale
        const box = new THREE.Box3().setFromObject(obj);
        const center = box.getCenter(new THREE.Vector3());
        const size = box.getSize(new THREE.Vector3());

        const maxDim = Math.max(size.x, size.y, size.z);
        const scale = 3.6 / (maxDim || 1);
        obj.scale.set(scale, scale, scale);

        obj.position.x -= center.x * scale;
        obj.position.y -= center.y * scale;
        obj.position.z -= center.z * scale;

        // Record per-child original local position and radial explode vector for Exploded View
        let partIdx = 0;
        obj.traverse((child) => {
          if (child.isMesh) {
            child.userData.origPos = child.position.clone();
            const childBox = new THREE.Box3().setFromObject(child);
            const childCenter = childBox.getCenter(new THREE.Vector3());
            // Direction outward from assembly origin (world center is at 0,0,0)
            const dir = childCenter.clone();
            if (dir.lengthSq() < 0.0001) {
              // Fallback for centered components: distribute along radial angles
              const angle = (partIdx * Math.PI * 2) / 6;
              dir.set(Math.cos(angle), (partIdx % 2 === 0 ? 0.6 : -0.6), Math.sin(angle));
            } else {
              dir.normalize();
            }
            child.userData.explodeDir = dir;
            partIdx++;
          }
        });

        scene.add(obj);

        setMeshStats({
          vertices: vCount,
          faces: Math.floor(fCount),
          dimensions: `${size.x.toFixed(2)} × ${size.y.toFixed(2)} × ${size.z.toFixed(2)}`,
        });
      };

      // Load with companion MTL file if available, with graceful fallback to plain OBJ
      const mtlUrl = url.replace(/\.obj(\?.*)?$/i, (match, query) => '.mtl' + (query || ''));
      const mtlLoader = new MTLLoader();
      mtlLoader.load(
        mtlUrl,
        (materials) => {
          materials.preload();
          const loader = new OBJLoader();
          loader.setMaterials(materials);
          loader.load(url, setupLoadedObject, undefined, (err) => {
            console.warn('OBJ load with MTL failed, falling back to standalone OBJ', err);
            new OBJLoader().load(url, setupLoadedObject);
          });
        },
        undefined,
        () => {
          new OBJLoader().load(url, setupLoadedObject);
        }
      );

      // Animation Loop
      let animationFrameId;
      const animate = () => {
        animationFrameId = requestAnimationFrame(animate);
        if (currentMesh && autoRotateRef.current) {
          currentMesh.rotation.y += 0.004;
        }
        controls.update();
        renderer.render(scene, camera);
      };
      animate();

      // Responsive Resize Observer
      const resizeObserver = new ResizeObserver((entries) => {
        for (const entry of entries) {
          const w = entry.contentRect.width;
          const h = entry.contentRect.height;
          if (w > 0 && h > 0) {
            camera.aspect = w / h;
            camera.updateProjectionMatrix();
            renderer.setSize(w, h);
          }
        }
      });
      resizeObserver.observe(container);

      threeCleanupRef.current = () => {
        cancelAnimationFrame(animationFrameId);
        resizeObserver.disconnect();
        controls.dispose();
        renderer.dispose();
        if (renderer.domElement && renderer.domElement.parentNode) {
          renderer.domElement.parentNode.removeChild(renderer.domElement);
        }
      };
    } catch (e) {
      console.error('Three.js failed to initialize', e);
      setError('Three.js 3D viewport initialization failed: ' + e.message);
    }
  };

  const toggleWireframe = () => {
    const nextState = !isWireframe;
    setIsWireframe(nextState);
    if (meshRef.current) {
      meshRef.current.traverse((child) => {
        if (child.isMesh && child.material) {
          const mats = Array.isArray(child.material) ? child.material : [child.material];
          mats.forEach((m) => {
            if (m) m.wireframe = nextState;
          });
        }
      });
    }
  };

  const toggleAutoRotate = () => {
    setAutoRotate((prev) => {
      const next = !prev;
      autoRotateRef.current = next;
      return next;
    });
  };

  const resetCamera = () => {
    if (cameraRef.current && controlsRef.current) {
      cameraRef.current.position.set(0, 3, 7);
      controlsRef.current.target.set(0, 0, 0);
      controlsRef.current.update();
    }
  };

  const applyExplode = (factor) => {
    if (!meshRef.current) return;
    meshRef.current.traverse((child) => {
      if (child.isMesh && child.userData.origPos && child.userData.explodeDir) {
        child.position.copy(child.userData.origPos).addScaledVector(child.userData.explodeDir, factor * 0.85);
      }
    });
  };

  const toggleExplode = () => {
    const next = !isExploded;
    setIsExploded(next);
    applyExplode(next ? explodeFactor : 0.0);
  };

  // ── Material & Modifier Panel helpers ─────────────────────────────────────

  // Fetch the list of objects in the scene when the panel opens
  const loadSceneObjects = () => {
    if (!cleanName || fileType !== 'obj') return;
    const targetPath = workspacePath ? `${workspacePath}/${cleanName}` : cleanName;
    fetch('/api/blender/modify', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ artifact_obj_path: targetPath, action: 'list_objects' }),
    })
      .then((r) => r.json())
      .then((data) => {
        const objs = data?.result?.objects || [];
        setSceneObjects(objs);
      })
      .catch(() => setSceneObjects([]));
  };

  const toggleMatPanel = () => {
    const next = !showMatPanel;
    setShowMatPanel(next);
    if (next) loadSceneObjects();
  };

  // Check if a child mesh matches the targeted object (or all if none selected)
  const isTargetMesh = (child) => {
    if (!matObjName || matObjName.trim() === '') return true;
    const target = matObjName.trim().toLowerCase();
    const childName = (child.name || '').trim().toLowerCase();
    const parentName = (child.parent?.name || '').trim().toLowerCase();
    const userObjName = (child.userData?.objectName || '').trim().toLowerCase();
    if (childName && (childName === target || childName.includes(target) || target.includes(childName))) return true;
    if (parentName && (parentName === target || parentName.includes(target) || target.includes(parentName))) return true;
    if (userObjName && (userObjName === target || userObjName.includes(target) || target.includes(userObjName))) return true;
    return false;
  };

  // Sync controls to targeted object's existing material when target changes
  const handleTargetObjectChange = (selectedName) => {
    setMatObjName(selectedName);
    if (!selectedName || !meshRef.current) return;

    const target = selectedName.trim().toLowerCase();
    let foundMat = null;
    meshRef.current.traverse((child) => {
      if (foundMat) return;
      if (child.isMesh && child.material) {
        const childName = (child.name || '').trim().toLowerCase();
        const parentName = (child.parent?.name || '').trim().toLowerCase();
        const userObjName = (child.userData?.objectName || '').trim().toLowerCase();
        if (
          (childName && (childName === target || childName.includes(target) || target.includes(childName))) ||
          (parentName && (parentName === target || parentName.includes(target) || target.includes(parentName))) ||
          (userObjName && (userObjName === target || userObjName.includes(target) || target.includes(userObjName)))
        ) {
          foundMat = Array.isArray(child.material) ? child.material[0] : child.material;
        }
      }
    });

    if (foundMat && foundMat.color) {
      const hex = '#' + foundMat.color.getHexString();
      setMatHexColor(hex);
      if (typeof foundMat.metalness === 'number') {
        setMatMetalness(foundMat.metalness);
      }
      if (typeof foundMat.roughness === 'number') {
        setMatRoughness(foundMat.roughness);
      }
    }
  };

  // Apply hex color to viewport Three.js mesh in real-time (live preview)
  const applyLiveColor = (hex) => {
    setMatHexColor(hex);
    if (!meshRef.current) return;
    const r = parseInt(hex.slice(1, 3), 16) / 255;
    const g = parseInt(hex.slice(3, 5), 16) / 255;
    const b = parseInt(hex.slice(5, 7), 16) / 255;
    meshRef.current.traverse((child) => {
      if (child.isMesh && child.material && isTargetMesh(child)) {
        if (!child.userData.isClonedMat) {
          child.material = Array.isArray(child.material)
            ? child.material.map((m) => m.clone())
            : child.material.clone();
          child.userData.isClonedMat = true;
        }
        if (Array.isArray(child.material)) {
          child.material.forEach((m) => m.color.setRGB(r, g, b));
        } else {
          child.material.color.setRGB(r, g, b);
        }
      }
    });
  };

  const applyLiveMetalness = (val) => {
    setMatMetalness(val);
    if (!meshRef.current) return;
    meshRef.current.traverse((child) => {
      if (child.isMesh && child.material && isTargetMesh(child)) {
        if (!child.userData.isClonedMat) {
          child.material = Array.isArray(child.material)
            ? child.material.map((m) => m.clone())
            : child.material.clone();
          child.userData.isClonedMat = true;
        }
        if (Array.isArray(child.material)) {
          child.material.forEach((m) => { m.metalness = val; });
        } else {
          child.material.metalness = val;
        }
      }
    });
  };

  const applyLiveRoughness = (val) => {
    setMatRoughness(val);
    if (!meshRef.current) return;
    meshRef.current.traverse((child) => {
      if (child.isMesh && child.material && isTargetMesh(child)) {
        if (!child.userData.isClonedMat) {
          child.material = Array.isArray(child.material)
            ? child.material.map((m) => m.clone())
            : child.material.clone();
          child.userData.isClonedMat = true;
        }
        if (Array.isArray(child.material)) {
          child.material.forEach((m) => { m.roughness = val; });
        } else {
          child.material.roughness = val;
        }
      }
    });
  };

  const applyLiveEmission = (val) => {
    setMatEmission(val);
    if (!meshRef.current) return;
    meshRef.current.traverse((child) => {
      if (child.isMesh && child.material && isTargetMesh(child)) {
        if (!child.userData.isClonedMat) {
          child.material = Array.isArray(child.material)
            ? child.material.map((m) => m.clone())
            : child.material.clone();
          child.userData.isClonedMat = true;
        }
        const r2 = parseInt(matHexColor.slice(1, 3), 16) / 255;
        const g2 = parseInt(matHexColor.slice(3, 5), 16) / 255;
        const b2 = parseInt(matHexColor.slice(5, 7), 16) / 255;
        const mats = Array.isArray(child.material) ? child.material : [child.material];
        mats.forEach((m) => {
          if (m.emissive) {
            m.emissive.setRGB(r2 * val, g2 * val, b2 * val);
            m.emissiveIntensity = val;
          }
        });
      }
    });
  };

  const callBlenderModify = (action, extraParams = {}) => {
    if (!cleanName || fileType !== 'obj') return;
    setMatOpBusy(true);
    setMatOpResult(null);
    setMatOpError(null);

    const targetPath = workspacePath ? `${workspacePath}/${cleanName}` : cleanName;
    const body = {
      artifact_obj_path: targetPath,
      action,
      hex_color: matHexColor,
      metalness: matMetalness,
      roughness: matRoughness,
      emission_strength: matEmission,
      modifier_type: modifierType,
      strength: modifierStrength,
      object_name: matObjName,
      ...extraParams,
    };

    fetch('/api/blender/modify', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
      .then((r) => r.json())
      .then((data) => {
        if (data.error) {
          setMatOpError(data.error);
        } else {
          const exitCode = data?.result?.exit_code;
          const ok = exitCode === 0;
          setMatOpResult(ok
            ? `✓ ${action === 'set_color' ? 'Color applied' : action === 'add_modifier' ? `Modifier '${modifierType}' applied` : 'Done'} in ${data?.result?.duration_sec ?? '?'}s — reload viewport to see`
            : `Blender exit ${exitCode}: ${(data?.result?.stderr || '').slice(0, 200)}`
          );
          if (!ok) setMatOpError(`Exit code ${exitCode}`);
        }
        setMatOpBusy(false);
        // Refresh scene object list
        loadSceneObjects();
      })
      .catch((e) => {
        setMatOpError(e.message || 'Network error');
        setMatOpBusy(false);
      });
  };

  const reloadViewport = () => {
    if (fileType === 'obj' && cleanName) {
      const freshUrl = fileUrl.includes('?') ? `${fileUrl}&_t=${Date.now()}` : `${fileUrl}?_t=${Date.now()}`;
      startThreeJS(freshUrl);
    }
  };

  // ── end Material & Modifier Panel helpers ─────────────────────────────────

  const copyToClipboard = () => {
    navigator.clipboard.writeText(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  // Robust RFC 4180 CSV Parser (handles quoted strings, commas, newlines)
  const parseCSV = (csvText) => {
    if (!csvText || !csvText.trim()) return { headers: [], rows: [] };
    const lines = csvText.trim().split(/\r?\n/).filter((l) => l.trim().length > 0);
    if (lines.length === 0) return { headers: [], rows: [] };

    const parseLine = (line) => {
      const result = [];
      let cur = '';
      let inQuotes = false;
      for (let i = 0; i < line.length; i++) {
        const c = line[i];
        if (c === '"') {
          if (inQuotes && line[i + 1] === '"') {
            cur += '"';
            i++;
          } else {
            inQuotes = !inQuotes;
          }
        } else if (c === ',' && !inQuotes) {
          result.push(cur.trim());
          cur = '';
        } else {
          cur += c;
        }
      }
      result.push(cur.trim());
      return result;
    };

    const headers = parseLine(lines[0]);
    const rows = lines.slice(1).map(parseLine);
    return { headers, rows };
  };

  // High-Quality Client-Side Markdown Formatter with Table, Code, and Section Support
  const renderFormattedMarkdown = (text) => {
    if (!text) return null;
    const lines = text.split(/\r?\n/);
    const elements = [];
    let tableRows = [];
    let inTable = false;
    let inCode = false;
    let codeLines = [];
    let codeLang = '';

    const flushTable = (key) => {
      if (tableRows.length === 0) return;
      const headers = tableRows[0];
      const dataRows = tableRows.slice(1);
      elements.push(html`
        <div key=${key} className="csv-table-wrapper" style=${{ margin: '14px 0' }}>
          <table className="csv-spatial-table">
            <thead>
              <tr>
                ${headers.map((h, hi) => html`<th key=${hi}>${h.trim()}</th>`)}
              </tr>
            </thead>
            <tbody>
              ${dataRows.map((r, ri) => html`
                <tr key=${ri}>
                  ${r.map((col, ci) => html`<td key=${ci}>${col.trim()}</td>`)}
                </tr>
              `)}
            </tbody>
          </table>
        </div>
      `);
      tableRows = [];
      inTable = false;
    };

    const flushCode = (key) => {
      if (codeLines.length === 0) return;
      const codeText = codeLines.join('\n');
      elements.push(html`
        <div key=${key} className="code-viewport-container" style=${{ margin: '14px 0' }}>
          <div className="code-toolbar">
            <span>${codeLang ? codeLang.toUpperCase() : 'CODE'}</span>
            <button
              className="btn btn-secondary"
              style=${{ padding: '2px 8px', fontSize: '10px' }}
              onClick=${() => navigator.clipboard.writeText(codeText)}
            >
              Copy
            </button>
          </div>
          <pre className="code-pre" style=${{ maxHeight: '350px' }}><code>${codeText}</code></pre>
        </div>
      `);
      codeLines = [];
      inCode = false;
      codeLang = '';
    };

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];

      // Code Block Boundary
      if (line.trim().startsWith('```')) {
        if (inCode) {
          flushCode(`code-${i}`);
        } else {
          if (inTable) flushTable(`table-${i}`);
          inCode = true;
          codeLang = line.trim().replace(/^```/, '').trim();
        }
        continue;
      }

      if (inCode) {
        codeLines.push(line);
        continue;
      }

      // Markdown Table Row
      if (line.trim().startsWith('|') && line.trim().endsWith('|')) {
        const cells = line.split('|').slice(1, -1);
        // Skip separator row like |---|---|
        if (cells.every((c) => /^[\s-:]+$/.test(c))) {
          continue;
        }
        inTable = true;
        tableRows.push(cells);
        continue;
      } else if (inTable) {
        flushTable(`table-${i}`);
      }

      // Headers
      if (line.startsWith('# ')) {
        elements.push(html`<h1 key=${i} style=${{ color: '#fff', fontSize: '20px', margin: '18px 0 10px', borderBottom: '1px solid var(--border-glass)', paddingBottom: '6px' }}>${line.replace('# ', '')}</h1>`);
      } else if (line.startsWith('## ')) {
        elements.push(html`<h2 key=${i} style=${{ color: 'var(--accent-cyan)', fontSize: '16px', margin: '16px 0 8px' }}>${line.replace('## ', '')}</h2>`);
      } else if (line.startsWith('### ')) {
        elements.push(html`<h3 key=${i} style=${{ color: '#cbd5e1', fontSize: '14px', margin: '12px 0 6px' }}>${line.replace('### ', '')}</h3>`);
      } else if (line.startsWith('> ')) {
        elements.push(html`<blockquote key=${i} style=${{ borderLeft: '3px solid var(--accent-primary)', margin: '10px 0', padding: '6px 12px', background: 'rgba(59, 130, 246, 0.08)', color: '#93c5fd', borderRadius: '0 4px 4px 0' }}>${line.replace('> ', '')}</blockquote>`);
      } else if (line.startsWith('- ') || line.startsWith('* ')) {
        elements.push(html`<li key=${i} style=${{ marginLeft: '20px', color: '#e2e8f0', margin: '3px 0' }}>${line.replace(/^[-*]\s+/, '')}</li>`);
      } else if (line.trim() === '---') {
        elements.push(html`<hr key=${i} style=${{ border: 'none', borderTop: '1px solid var(--border-glass)', margin: '16px 0' }} />`);
      } else if (line.trim()) {
        elements.push(html`<p key=${i} style=${{ margin: '6px 0', color: '#e2e8f0', lineHeight: '1.6' }}>${line}</p>`);
      }
    }

    if (inTable) flushTable('table-end');
    if (inCode) flushCode('code-end');

    return elements;
  };

  const formatFileSize = (bytes) => {
    if (!bytes) return '0 B';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
  };

  const totalLines = content ? content.split(/\r?\n/).length : 0;

  return html`
    <div className="modal-overlay" onClick=${onClose}>
      <div className="modal-content" style=${{ maxWidth: '1280px', width: '92vw', height: '88vh' }} onClick=${(e) => e.stopPropagation()}>
        <!-- Modal Header with Full Data Telemetry -->
        <div className="modal-header">
          <div style=${{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <${Icon}
              name=${fileType === 'obj' ? 'box' : isImage ? 'eye' : fileType === 'csv' ? 'activity' : fileType === 'py' ? 'code' : 'fileText'}
              size=${20}
            />
            <div>
              <div style=${{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style=${{ fontSize: '15px', fontWeight: 600, color: '#fff' }}>${cleanName}</span>
                <span className="pill pending" style=${{ fontSize: '10px', textTransform: 'uppercase' }}>
                  ${fileType === 'obj' ? '3D MESH' : isImage ? 'IMAGE ARTIFACT' : fileType === 'csv' ? 'CSV DATASET' : fileType === 'py' ? 'PYTHON SCRIPT' : 'DOCUMENT'}
                </span>
              </div>
              <div style=${{ fontSize: '11px', color: '#94a3b8', marginTop: '2px' }}>
                Size: <strong>${formatFileSize(fileSizeBytes)}</strong>
                ${imageDims.width > 0 ? html` · Resolution: <strong>${imageDims.width} × ${imageDims.height} px</strong>` : ''}
                ${totalLines > 0 ? html` · Lines: <strong>${totalLines.toLocaleString()}</strong>` : ''}
                ${meshStats.vertices > 0 ? html` · Vertices: <strong>${meshStats.vertices.toLocaleString()}</strong> · Faces: <strong>${meshStats.faces.toLocaleString()}</strong>` : ''}
              </div>
            </div>
          </div>

          <div style=${{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <!-- View Mode Switcher for CSV & Markdown -->
            ${(fileType === 'csv' || fileType === 'md' || fileType === 'txt') && !loading && !error && html`
              <div style=${{ display: 'flex', background: 'rgba(0,0,0,0.4)', borderRadius: '6px', padding: '2px', border: '1px solid var(--border-glass)' }}>
                <button
                  className=${`btn ${viewMode === 'formatted' ? 'btn-primary' : 'btn-secondary'}`}
                  style=${{ padding: '3px 10px', fontSize: '11px', borderRadius: '4px' }}
                  onClick=${() => setViewMode('formatted')}
                >
                  ${fileType === 'csv' ? 'Table Grid' : 'Formatted'}
                </button>
                <button
                  className=${`btn ${viewMode === 'raw' ? 'btn-primary' : 'btn-secondary'}`}
                  style=${{ padding: '3px 10px', fontSize: '11px', borderRadius: '4px' }}
                  onClick=${() => setViewMode('raw')}
                >
                  Raw Source
                </button>
              </div>
            `}

            <button className="btn btn-secondary" onClick=${copyToClipboard} title="Copy entire content">
              <${Icon} name="copy" size=${13} />
              <span>${copied ? 'Copied!' : 'Copy'}</span>
            </button>

            <a className="btn btn-secondary" href=${fileUrl} download title="Download raw artifact">
              <${Icon} name="download" size=${13} />
              <span>Download</span>
            </a>

            <button className="btn-icon" onClick=${onClose} title="Close Viewport">
              <${Icon} name="close" size=${16} />
            </button>
          </div>
        </div>

        <!-- Modal Body: Flexible Full-Height Viewport -->
        <div className="modal-body" style=${{ padding: '16px', display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0, overflow: 'auto' }}>
          ${loading && html`
            <div className="empty-state" style=${{ flex: 1 }}>
              <div className="empty-state-icon" style=${{ animation: 'spin 1.5s infinite linear' }}>
                <${Icon} name="refresh" size=${32} />
              </div>
              <div className="empty-state-text">Loading artifact viewport from disk...</div>
            </div>
          `}

          ${error && html`
            <div className="empty-state" style=${{ flex: 1 }}>
              <div className="empty-state-text" style=${{ color: '#f43f5e', fontSize: '14px', maxWidth: '600px' }}>
                <div style=${{ fontWeight: 600, marginBottom: '6px' }}>Artifact Load Error</div>
                <div>${error}</div>
                <div style=${{ fontSize: '11px', color: '#94a3b8', marginTop: '10px' }}>Target URL: <code>${fileUrl}</code></div>
              </div>
            </div>
          `}

          <!-- 1. 3D OBJ Viewport -->
          ${fileType === 'obj' && !loading && !error && html`
            <div style=${{ display: 'flex', flex: 1, gap: '12px', minHeight: '520px' }}>

              <!-- Canvas area -->
              <div className="viewport-3d-container" style=${{ flex: 1, minHeight: '520px', position: 'relative' }}>
                <div ref=${canvasRef} className="viewport-3d-canvas"></div>
                
                <div className="viewport-3d-controls">
                  <button
                    className=${isWireframe ? 'active' : ''}
                    onClick=${toggleWireframe}
                    title="Toggle wireframe rendering mode"
                  >
                    ${isWireframe ? 'Solid' : 'Wireframe'}
                  </button>
                  <button
                    className=${autoRotate ? 'active' : ''}
                    onClick=${toggleAutoRotate}
                    title="Toggle continuous turntable rotation"
                  >
                    ${autoRotate ? 'Pause Rotation' : 'Auto Rotate'}
                  </button>
                  <button onClick=${resetCamera} title="Reset camera position">
                    Reset View
                  </button>
                  <button
                    className=${isExploded ? 'active' : ''}
                    onClick=${toggleExplode}
                    title="Toggle Exploded Assembly View"
                    style=${{
                      background: isExploded ? 'rgba(56, 189, 248, 0.25)' : '',
                      borderColor: isExploded ? '#38bdf8' : '',
                      color: isExploded ? '#38bdf8' : '',
                    }}
                  >
                    💥 ${isExploded ? 'Collapse View' : 'Exploded View'}
                  </button>

                  ${isExploded && html`
                    <div style=${{ display: 'flex', alignItems: 'center', gap: '6px', background: 'rgba(0,0,0,0.5)', padding: '2px 8px', borderRadius: '4px', border: '1px solid rgba(56, 189, 248, 0.3)' }}>
                      <span style=${{ fontSize: '11px', color: '#94a3b8' }}>Offset:</span>
                      <input
                        type="range"
                        min="0.2"
                        max="2.5"
                        step="0.1"
                        value=${explodeFactor}
                        onInput=${(e) => {
                          const val = parseFloat(e.target.value);
                          setExplodeFactor(val);
                          applyExplode(val);
                        }}
                        style=${{ width: '70px', height: '4px', cursor: 'pointer', accentColor: '#38bdf8' }}
                      />
                      <span style=${{ fontSize: '10px', color: '#38bdf8', minWidth: '24px', fontFamily: 'var(--font-mono)' }}>${explodeFactor.toFixed(1)}x</span>
                    </div>
                  `}
                  <button
                    className=${showMatPanel ? 'active' : ''}
                    onClick=${toggleMatPanel}
                    title="Open Material & Modifier panel"
                    style=${{ background: showMatPanel ? 'rgba(168,85,247,0.25)' : '', borderColor: showMatPanel ? '#a855f7' : '' }}
                  >
                    🎨 Materials
                  </button>
                </div>

                <div className="viewport-3d-hint">
                  Left click to orbit · Scroll to zoom · Right click to pan
                  ${meshStats.dimensions ? ` · Bounding Box: ${meshStats.dimensions}` : ''}
                </div>
              </div>

              <!-- Material & Modifier Panel -->
              ${showMatPanel && html`
                <div style=${{
                  width: '260px',
                  flexShrink: 0,
                  background: 'rgba(10,14,23,0.95)',
                  border: '1px solid rgba(168,85,247,0.3)',
                  borderRadius: '10px',
                  padding: '14px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '14px',
                  overflowY: 'auto',
                  fontSize: '12px',
                }}>

                  <!-- Panel Title -->
                  <div style=${{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <span style=${{ fontWeight: 700, color: '#a855f7', fontSize: '13px', letterSpacing: '0.03em' }}>
                      🎨 Material & Modifiers
                    </span>
                    <button
                      onClick=${() => setShowMatPanel(false)}
                      style=${{ background: 'none', border: 'none', color: '#64748b', cursor: 'pointer', fontSize: '14px' }}
                    >✕</button>
                  </div>

                  <!-- Object Selector -->
                  <div>
                    <div style=${{ color: '#94a3b8', marginBottom: '5px', fontWeight: 600 }}>Target Object</div>
                    <select
                      value=${matObjName}
                      onChange=${(e) => handleTargetObjectChange(e.target.value)}
                      style=${{ width: '100%', background: '#0f172a', border: '1px solid #334155', color: '#e2e8f0', borderRadius: '5px', padding: '5px 8px', fontSize: '11px' }}
                    >
                      <option value="">All Objects</option>
                      ${sceneObjects.map((o, i) => html`
                        <option key=${i} value=${o.name}>${o.name} (${o.vertices}v)</option>
                      `)}
                    </select>
                    ${sceneObjects.length === 0 && html`
                      <div style=${{ fontSize: '10px', color: '#64748b', marginTop: '4px' }}>Loading objects...</div>
                    `}
                  </div>

                  <!-- Divider -->
                  <div style=${{ borderTop: '1px solid #1e293b' }}></div>

                  <!-- BASE COLOR -->
                  <div>
                    <div style=${{ color: '#94a3b8', marginBottom: '8px', fontWeight: 600 }}>Base Color</div>
                    <div style=${{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                      <input
                        type="color"
                        value=${matHexColor}
                        onInput=${(e) => applyLiveColor(e.target.value)}
                        onChange=${(e) => applyLiveColor(e.target.value)}
                        style=${{ width: '48px', height: '36px', border: 'none', borderRadius: '5px', cursor: 'pointer', background: 'none' }}
                      />
                      <input
                        type="text"
                        value=${matHexColor}
                        onInput=${(e) => { if (/^#[0-9a-fA-F]{6}$/.test(e.target.value)) applyLiveColor(e.target.value); }}
                        style=${{ flex: 1, background: '#0f172a', border: '1px solid #334155', color: '#e2e8f0', borderRadius: '5px', padding: '5px 8px', fontSize: '11px', fontFamily: 'monospace' }}
                      />
                    </div>
                    <!-- Swatches -->
                    <div style=${{ display: 'flex', gap: '5px', marginTop: '8px', flexWrap: 'wrap' }}>
                      ${['#7ec8e3','#f97316','#a855f7','#22c55e','#ef4444','#eab308','#e2e8f0','#1e293b','#b45309','#0ea5e9'].map((c, i) => html`
                        <div
                          key=${i}
                          onClick=${() => applyLiveColor(c)}
                          title=${c}
                          style=${{
                            width: '18px', height: '18px', borderRadius: '4px', background: c, cursor: 'pointer',
                            border: matHexColor === c ? '2px solid #fff' : '1px solid rgba(255,255,255,0.15)',
                            flexShrink: 0,
                          }}
                        ></div>
                      `)}
                    </div>
                  </div>

                  <!-- Metalness -->
                  <div>
                    <div style=${{ display: 'flex', justifyContent: 'space-between', color: '#94a3b8', marginBottom: '5px', fontWeight: 600 }}>
                      <span>Metalness</span>
                      <span style=${{ color: '#a855f7' }}>${matMetalness.toFixed(2)}</span>
                    </div>
                    <input type="range" min="0" max="1" step="0.01"
                      value=${matMetalness}
                      onInput=${(e) => applyLiveMetalness(parseFloat(e.target.value))}
                      style=${{ width: '100%', accentColor: '#a855f7' }}
                    />
                  </div>

                  <!-- Roughness -->
                  <div>
                    <div style=${{ display: 'flex', justifyContent: 'space-between', color: '#94a3b8', marginBottom: '5px', fontWeight: 600 }}>
                      <span>Roughness</span>
                      <span style=${{ color: '#a855f7' }}>${matRoughness.toFixed(2)}</span>
                    </div>
                    <input type="range" min="0" max="1" step="0.01"
                      value=${matRoughness}
                      onInput=${(e) => applyLiveRoughness(parseFloat(e.target.value))}
                      style=${{ width: '100%', accentColor: '#a855f7' }}
                    />
                  </div>

                  <!-- Emission -->
                  <div>
                    <div style=${{ display: 'flex', justifyContent: 'space-between', color: '#94a3b8', marginBottom: '5px', fontWeight: 600 }}>
                      <span>Emission</span>
                      <span style=${{ color: '#a855f7' }}>${matEmission.toFixed(2)}</span>
                    </div>
                    <input type="range" min="0" max="5" step="0.1"
                      value=${matEmission}
                      onInput=${(e) => applyLiveEmission(parseFloat(e.target.value))}
                      style=${{ width: '100%', accentColor: '#a855f7' }}
                    />
                  </div>

                  <!-- Apply Color Button -->
                  <button
                    onClick=${() => callBlenderModify('set_color')}
                    disabled=${matOpBusy}
                    style=${{
                      width: '100%', padding: '8px', borderRadius: '7px', border: 'none', cursor: matOpBusy ? 'not-allowed' : 'pointer',
                      background: matOpBusy ? '#1e293b' : 'linear-gradient(135deg, #7c3aed, #a855f7)',
                      color: '#fff', fontWeight: 700, fontSize: '12px',
                    }}
                  >
                    ${matOpBusy ? '⏳ Applying…' : '🎨 Bake Color to File'}
                  </button>

                  <!-- Divider -->
                  <div style=${{ borderTop: '1px solid #1e293b' }}></div>

                  <!-- MODIFIER SECTION -->
                  <div>
                    <div style=${{ color: '#94a3b8', marginBottom: '8px', fontWeight: 600 }}>Modifier</div>
                    <select
                      value=${modifierType}
                      onChange=${(e) => setModifierType(e.target.value)}
                      style=${{ width: '100%', background: '#0f172a', border: '1px solid #334155', color: '#e2e8f0', borderRadius: '5px', padding: '5px 8px', fontSize: '11px', marginBottom: '8px' }}
                    >
                      <option value="subdivision">Subdivision Surface</option>
                      <option value="bevel">Bevel Edges</option>
                      <option value="solidify">Solidify Shell</option>
                      <option value="wireframe">Wireframe Cage</option>
                      <option value="decimate">Decimate (Reduce Poly)</option>
                      <option value="displace">Displace (Noise Bump)</option>
                    </select>
                    <div style=${{ display: 'flex', justifyContent: 'space-between', color: '#94a3b8', marginBottom: '5px' }}>
                      <span>${modifierType === 'decimate' ? 'Ratio' : modifierType === 'subdivision' ? 'Levels' : 'Strength'}</span>
                      <span style=${{ color: '#38bdf8' }}>${modifierStrength.toFixed(2)}</span>
                    </div>
                    <input type="range"
                      min=${modifierType === 'decimate' ? '0.05' : modifierType === 'subdivision' ? '1' : '0.01'}
                      max=${modifierType === 'subdivision' ? '4' : modifierType === 'decimate' ? '1' : '2'}
                      step=${modifierType === 'subdivision' ? '1' : '0.01'}
                      value=${modifierStrength}
                      onInput=${(e) => setModifierStrength(parseFloat(e.target.value))}
                      style=${{ width: '100%', accentColor: '#38bdf8' }}
                    />
                  </div>

                  <!-- Apply Modifier Button -->
                  <button
                    onClick=${() => callBlenderModify('add_modifier')}
                    disabled=${matOpBusy}
                    style=${{
                      width: '100%', padding: '8px', borderRadius: '7px', border: 'none', cursor: matOpBusy ? 'not-allowed' : 'pointer',
                      background: matOpBusy ? '#1e293b' : 'linear-gradient(135deg, #0369a1, #38bdf8)',
                      color: '#fff', fontWeight: 700, fontSize: '12px',
                    }}
                  >
                    ${matOpBusy ? '⏳ Applying…' : '⚙️ Apply Modifier to File'}
                  </button>

                  <!-- Reload Button -->
                  <button
                    onClick=${reloadViewport}
                    style=${{
                      width: '100%', padding: '7px', borderRadius: '7px', border: '1px solid #334155', cursor: 'pointer',
                      background: '#0f172a', color: '#94a3b8', fontWeight: 600, fontSize: '11px',
                    }}
                  >
                    🔄 Reload 3D Viewport
                  </button>

                  <!-- Op Result -->
                  ${matOpResult && html`
                    <div style=${{ background: 'rgba(34,197,94,0.1)', border: '1px solid rgba(34,197,94,0.3)', borderRadius: '6px', padding: '8px', color: '#86efac', fontSize: '11px', lineHeight: '1.5' }}>
                      ${matOpResult}
                    </div>
                  `}
                  ${matOpError && html`
                    <div style=${{ background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: '6px', padding: '8px', color: '#fca5a5', fontSize: '11px' }}>
                      ⚠️ ${matOpError}
                    </div>
                  `}

                  <!-- Scene Objects Summary -->
                  ${sceneObjects.length > 0 && html`
                    <div>
                      <div style=${{ color: '#64748b', marginBottom: '5px', fontSize: '10px', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                        Scene Objects (${sceneObjects.length})
                      </div>
                      ${sceneObjects.map((o, i) => html`
                        <div key=${i} style=${{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', borderBottom: '1px solid #0f172a', fontSize: '10px' }}>
                          <span style=${{ color: '#e2e8f0', fontFamily: 'monospace' }}>${o.name}</span>
                          <span style=${{ color: '#64748b' }}>${o.vertices}v · ${o.faces}f</span>
                        </div>
                      `)}
                    </div>
                  `}

                </div>
              `}

            </div>
          `}

          <!-- 2. CSV Table Viewport -->
          ${fileType === 'csv' && !loading && !error && (() => {
            if (viewMode === 'raw') {
              return html`
                <div className="code-viewport-container" style=${{ flex: 1, minHeight: '450px' }}>
                  <pre className="code-pre" style=${{ maxHeight: 'none', height: '100%' }}><code>${content}</code></pre>
                </div>
              `;
            }

            const { headers, rows } = parseCSV(content);
            const filteredRows = rows.filter((r) =>
              r.some((c) => c && c.toLowerCase().includes(csvFilter.toLowerCase()))
            );

            return html`
              <div className="csv-viewport-container" style=${{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
                <div className="csv-toolbar" style=${{ marginBottom: '10px' }}>
                  <div style=${{ fontSize: '12px', color: '#94a3b8' }}>
                    Total: <strong style=${{ color: '#fff' }}>${rows.length}</strong> rows × <strong style=${{ color: '#fff' }}>${headers.length}</strong> columns
                    ${csvFilter ? html` · Matching filter: <strong style=${{ color: 'var(--accent-cyan)' }}>${filteredRows.length}</strong>` : ''}
                  </div>
                  <input
                    type="text"
                    className="csv-search-input"
                    placeholder="Search all cells..."
                    value=${csvFilter}
                    onChange=${(e) => setCsvFilter(e.target.value)}
                  />
                </div>

                <div className="csv-table-wrapper" style=${{ flex: 1, overflow: 'auto', maxHeight: 'calc(88vh - 180px)' }}>
                  <table className="csv-spatial-table">
                    <thead>
                      <tr>
                        <th style=${{ width: '40px', textAlign: 'center', color: '#64748b' }}>#</th>
                        ${headers.map((h, i) => html`<th key=${i}>${h}</th>`)}
                      </tr>
                    </thead>
                    <tbody>
                      ${filteredRows.map((row, ri) => html`
                        <tr key=${ri}>
                          <td style=${{ textAlign: 'center', color: '#64748b', fontSize: '10px' }}>${ri + 1}</td>
                          ${row.map((col, ci) => html`<td key=${ci}>${col}</td>`)}
                        </tr>
                      `)}
                    </tbody>
                  </table>
                </div>
              </div>
            `;
          })()}

          <!-- 3. Python & JSON Code Viewport -->
          ${(fileType === 'py' || fileType === 'json') && !loading && !error && html`
            <div className="code-viewport-container" style=${{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
              <div className="code-toolbar">
                <span>${fileType.toUpperCase()} SOURCE CODE (${totalLines.toLocaleString()} lines)</span>
                <span style=${{ color: '#94a3b8' }}>UTF-8 · Python Standard Library</span>
              </div>
              <pre className="code-pre" style=${{ flex: 1, maxHeight: 'calc(88vh - 180px)', overflow: 'auto' }}><code>${content}</code></pre>
            </div>
          `}

          <!-- 4. Markdown Viewport -->
          ${(fileType === 'md' || fileType === 'txt') && !loading && !error && (() => {
            if (viewMode === 'raw') {
              return html`
                <div className="code-viewport-container" style=${{ flex: 1, minHeight: '450px' }}>
                  <pre className="code-pre" style=${{ maxHeight: 'none', height: '100%' }}><code>${content}</code></pre>
                </div>
              `;
            }

            return html`
              <div className="markdown-viewport-container" style=${{ flex: 1, overflowY: 'auto', maxHeight: 'calc(88vh - 180px)', paddingRight: '8px' }}>
                ${renderFormattedMarkdown(content)}
              </div>
            `;
          })()}

          <!-- 5. Image Viewport (Desktop Screenshots / Vision Captures) -->
          ${isImage && !loading && !error && html`
            <div style=${{
              flex: 1,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              minHeight: '480px',
              background: 'radial-gradient(ellipse at center, #0f172a 0%, #020617 100%)',
              borderRadius: '8px',
              border: '1px solid var(--border-glass)',
              padding: '24px',
              position: 'relative',
              overflow: 'auto',
            }}>
              <!-- Image Zoom Controls -->
              <div style=${{ position: 'absolute', top: '14px', right: '14px', display: 'flex', gap: '6px', zIndex: 10 }}>
                <button
                  className="btn btn-secondary"
                  style=${{ padding: '4px 10px', fontSize: '11px' }}
                  onClick=${() => setImageZoom((z) => Math.max(0.25, parseFloat((z - 0.25).toFixed(2))))}
                  title="Zoom Out"
                >
                  -
                </button>
                <button
                  className="btn btn-secondary"
                  style=${{ padding: '4px 10px', fontSize: '11px', minWidth: '55px' }}
                  onClick=${() => setImageZoom(1)}
                  title="Reset to 100%"
                >
                  ${Math.round(imageZoom * 100)}%
                </button>
                <button
                  className="btn btn-secondary"
                  style=${{ padding: '4px 10px', fontSize: '11px' }}
                  onClick=${() => setImageZoom((z) => Math.min(4, parseFloat((z + 0.25).toFixed(2))))}
                  title="Zoom In"
                >
                  +
                </button>
              </div>

              <!-- Main Image Display -->
              <div style=${{ overflow: 'auto', display: 'flex', alignItems: 'center', justifyContent: 'center', width: '100%', height: '100%' }}>
                <img
                  src=${fileUrl}
                  alt=${cleanName}
                  onLoad=${(e) => setImageDims({ width: e.target.naturalWidth, height: e.target.naturalHeight })}
                  style=${{
                    maxWidth: imageZoom === 1 ? '100%' : 'none',
                    maxHeight: imageZoom === 1 ? 'calc(88vh - 220px)' : 'none',
                    transform: `scale(${imageZoom})`,
                    transformOrigin: 'center center',
                    transition: 'transform 0.15s ease-out',
                    objectFit: 'contain',
                    borderRadius: '6px',
                    boxShadow: '0 10px 40px rgba(0,0,0,0.6)',
                  }}
                />
              </div>

              ${imageDims.width > 0 && html`
                <div style=${{
                  position: 'absolute',
                  bottom: '14px',
                  left: '16px',
                  fontSize: '11px',
                  color: '#94a3b8',
                  background: 'rgba(15,23,42,0.85)',
                  padding: '4px 12px',
                  borderRadius: '5px',
                  border: '1px solid #334155',
                  backdropFilter: 'blur(6px)',
                }}>
                  Native: <strong style=${{ color: '#e2e8f0' }}>${imageDims.width} × ${imageDims.height} px</strong> · Format: <strong style=${{ color: 'var(--accent-cyan)' }}>${fileType.toUpperCase()}</strong>
                </div>
              `}
            </div>
          `}
        </div>
      </div>
    </div>
  `;
}
