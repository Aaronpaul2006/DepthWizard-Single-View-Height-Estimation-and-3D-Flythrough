import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { PointerLockControls } from 'three/addons/controls/PointerLockControls.js';
import type { GridPoint, MeshData, Meta, ProfilePoint } from './terrain';
import { pickGrid } from './picking';
export type Surface = 'ortho' | 'elevation' | 'slope' | 'error';
const vertexShader = `
  attribute float slope; attribute float errorValue; attribute float errorValid;
  varying vec2 vUv; varying vec3 vNormal; varying float vHeight; varying float vSlope; varying float vError; varying float vValid;
  void main(){vUv=uv;vNormal=normalize(normalMatrix*normal);vHeight=position.y;vSlope=slope;
    vValid=errorValid;vError=errorValue;
    gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);}
`;
const fragmentShader = `
  uniform sampler2D ortho;uniform int mode;uniform float heightRange;uniform float errorRange;uniform float contourStep;uniform bool contours;uniform bool hillshade;
  uniform vec3 lightDir;
  varying vec2 vUv;varying vec3 vNormal;varying float vHeight;varying float vSlope;varying float vError;varying float vValid;
  vec3 ramp(float t){
    vec3 a=vec3(.12,.28,.23),b=vec3(.39,.53,.31),c=vec3(.74,.72,.47),d=vec3(.83,.81,.71);
    return t<.4?mix(a,b,t/.4):t<.75?mix(b,c,(t-.4)/.35):mix(c,d,(t-.75)/.25);
  }
  void main(){
    float h=clamp(vHeight/max(heightRange,.001),0.,1.);vec3 color;
    if(mode==0)color=texture2D(ortho,vUv).rgb;
    else if(mode==1)color=ramp(h);
    else if(mode==2){float s=clamp(vSlope/60.,0.,1.);color=s<.5?mix(vec3(.17,.52,.43),vec3(.95,.80,.37),s*2.):mix(vec3(.95,.80,.37),vec3(.85,.29,.22),(s-.5)*2.);if(vSlope<0.)color=vec3(.35);}
    else {float e=clamp(vError/max(errorRange,.001),-1.,1.);color=e<0.?mix(vec3(.89,.90,.85),vec3(.20,.46,.72),-e):mix(vec3(.89,.90,.85),vec3(.85,.32,.24),e);if(vValid<.999)color=vec3(.28,.30,.31);}
    float lighting=hillshade?(.62+.47*max(dot(normalize(vNormal),lightDir),0.)):1.;color*=lighting;
    if(contours){float v=vHeight/contourStep;float line=1.-smoothstep(0.,max(fwidth(v)*1.15,.008),abs(fract(v+.5)-.5));color=mix(color,color*.50,line*.55);}
    gl_FragColor=vec4(color,1.);
    #include <tonemapping_fragment>
    #include <colorspace_fragment>
  }
`;
export class TerrainViewer {
  readonly renderer: THREE.WebGLRenderer;
  readonly camera = new THREE.PerspectiveCamera(42, 1, 0.1, 100000);
  readonly scene = new THREE.Scene();
  readonly orbit: OrbitControls;
  readonly fly: PointerLockControls;
  readonly group = new THREE.Group();
  mode: 'orbit' | 'fly' = 'orbit';
  drawing = false;
  meta?: Meta;
  meshData?: MeshData;
  exaggeration = 1;
  // DepthWizard patch (VIEWER_CONTRACT): relative heights get world height h × 0.1 × extent.
  private baseScale = 1;
  onPick?: (point: GridPoint | null, click: boolean) => void;
  onPerformance?: (fps: number, ratio: number) => void;
  onHeading?: (angle: number) => void;
  onLock?: (locked: boolean) => void;
  onError?: (message: string) => void;
  private terrain?: THREE.Mesh<THREE.BufferGeometry, THREE.ShaderMaterial>;
  private base?: THREE.Mesh;
  private frame?: THREE.LineLoop;
  private grid?: THREE.GridHelper;
  private skirt?: THREE.Mesh;
  private texture?: THREE.Texture;
  private profileGroup = new THREE.Group();
  private marker?: THREE.Mesh;
  private keys = new Set<string>();
  private pointer = new THREE.Vector2();
  private raycaster = new THREE.Raycaster();
  private hoverDirty = false;
  private down = { x: 0, y: 0 };
  private worldLight = new THREE.Vector3(-0.5, 1, 0.4).normalize();
  private capRatio = Math.min(window.devicePixelRatio, 1.5);
  private slowWindows = 0;
  private frameId = 0;
  private resizeObserver: ResizeObserver;
  constructor(readonly host: HTMLElement) {
    this.renderer = new THREE.WebGLRenderer({
      antialias: false,
      alpha: false,
      powerPreference: 'high-performance',
    });
    this.renderer.setPixelRatio(this.capRatio);
    this.renderer.setClearColor('#172122');
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    host.prepend(this.renderer.domElement);
    this.renderer.domElement.setAttribute(
      'aria-label',
      'Interactive 3D terrain. Drag to orbit, scroll to zoom, or select Draw profile.',
    );
    this.renderer.domElement.tabIndex = 0;
    this.orbit = new OrbitControls(this.camera, this.renderer.domElement);
    this.orbit.enableDamping = true;
    this.orbit.dampingFactor = 0.08;
    this.orbit.maxPolarAngle = Math.PI * 0.495;
    this.orbit.minDistance = 1;
    this.fly = new PointerLockControls(this.camera, this.renderer.domElement);
    this.fly.pointerSpeed = 0.65;
    this.fly.addEventListener('lock', () => {
      this.keys.clear();
      this.onLock?.(true);
    });
    this.fly.addEventListener('unlock', () => {
      this.keys.clear();
      this.onLock?.(false);
    });
    this.scene.add(this.group);
    this.group.add(this.profileGroup);
    const ambient = new THREE.HemisphereLight('#e5ece4', '#363a2f', 2);
    this.scene.add(ambient);
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(host);
    this.renderer.domElement.addEventListener('pointermove', (e) => {
      const rect = this.renderer.domElement.getBoundingClientRect();
      this.pointer.set(
        ((e.clientX - rect.left) / rect.width) * 2 - 1,
        (-(e.clientY - rect.top) / rect.height) * 2 + 1,
      );
      this.hoverDirty = true;
    });
    this.renderer.domElement.addEventListener('pointerleave', () => {
      if (!this.fly.isLocked) {
        this.hoverDirty = false;
        this.onPick?.(null, false);
      }
    });
    this.renderer.domElement.addEventListener('pointerdown', (e) => {
      this.down = { x: e.clientX, y: e.clientY };
    });
    this.renderer.domElement.addEventListener('pointerup', (e) => {
      if (e.button !== 0 || Math.hypot(e.clientX - this.down.x, e.clientY - this.down.y) > 5)
        return;
      if (this.mode === 'fly' && !this.fly.isLocked) {
        // Call the browser API directly so promise-based WebViews cannot produce an unhandled rejection.
        try {
          const request = this.renderer.domElement.requestPointerLock();
          request?.catch(() =>
            this.onError?.(
              'Pointer lock was unavailable. Click the terrain to try again, or use Orbit.',
            ),
          );
        } catch {
          this.onError?.('Pointer lock is unavailable in this host.');
        }
        return;
      }
      this.pick(true);
    });
    document.addEventListener('pointerlockerror', () =>
      this.onError?.('Pointer lock was unavailable. Click the terrain to try again, or use Orbit.'),
    );
    window.addEventListener('keydown', this.keydown);
    window.addEventListener('keyup', this.keyup);
    window.addEventListener('blur', this.blur);
    this.renderer.domElement.addEventListener('webglcontextlost', (e) => {
      e.preventDefault();
      cancelAnimationFrame(this.frameId);
      this.onError?.('Graphics context lost. Reload the viewer to restore the terrain.');
    });
    this.resize();
    this.animate();
  }
  private keydown = (e: KeyboardEvent) => {
    if (this.fly.isLocked) {
      this.keys.add(e.code);
      if (['Space', 'KeyW', 'KeyA', 'KeyS', 'KeyD', 'KeyQ', 'KeyE'].includes(e.code))
        e.preventDefault();
    }
  };
  private keyup = (e: KeyboardEvent) => {
    this.keys.delete(e.code);
  };
  private blur = () => this.keys.clear();
  private resize() {
    const { width, height } = this.host.getBoundingClientRect();
    this.renderer.setSize(width, height);
    this.camera.aspect = width / Math.max(1, height);
    this.camera.updateProjectionMatrix();
  }
  async prepareTexture(blob: Blob) {
    const original = await createImageBitmap(blob);
    const max = Math.min(2048, this.renderer.capabilities.maxTextureSize),
      factor = Math.min(1, max / Math.max(original.width, original.height));
    const width = original.width,
      height = original.height;
    original.close();
    const bitmap = await createImageBitmap(blob, {
      imageOrientation: 'flipY',
      resizeWidth: Math.max(1, Math.round(width * factor)),
      resizeHeight: Math.max(1, Math.round(height * factor)),
      resizeQuality: 'high',
    });
    const texture = new THREE.Texture(bitmap);
    texture.flipY = false;
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.anisotropy = Math.min(4, this.renderer.capabilities.getMaxAnisotropy());
    texture.needsUpdate = true;
    return { texture, width, height };
  }
  setDataset(meta: Meta, mesh: MeshData, texture: THREE.Texture) {
    this.clearProfile();
    this.clearMarker();
    if (this.texture) {
      (this.texture.image as ImageBitmap).close?.();
      this.texture.dispose();
    }
    this.texture = texture;
    this.meta = meta;
    this.setMesh(mesh);
    this.exaggeration = 1;
    this.baseScale =
      meta.units === 'relative' ? 0.1 * Math.max(meta.width, meta.height) * meta.pixel_size_m : 1;
    this.group.scale.y = this.baseScale;
    for (const object of [this.base, this.grid, this.frame])
      if (object) {
        this.scene.remove(object);
        object.geometry.dispose();
        (object.material as THREE.Material).dispose();
      }
    const w = (meta.width - 1) * meta.pixel_size_m,
      d = (meta.height - 1) * meta.pixel_size_m,
      extent = Math.max(w, d),
      thickness = extent * 0.026;
    this.base = new THREE.Mesh(
      new THREE.BoxGeometry(w, thickness, d),
      new THREE.MeshStandardMaterial({ color: '#333f35', roughness: 1 }),
    );
    this.base.position.y = -thickness / 2 - extent * 0.002;
    this.scene.add(this.base);
    this.grid = new THREE.GridHelper(extent * 5, 50, '#344041', '#273233');
    this.grid.position.y = -thickness - extent * 0.002;
    this.scene.add(this.grid);
    const border = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(-w / 2, -0.1, -d / 2),
      new THREE.Vector3(w / 2, -0.1, -d / 2),
      new THREE.Vector3(w / 2, -0.1, d / 2),
      new THREE.Vector3(-w / 2, -0.1, d / 2),
    ]);
    this.frame = new THREE.LineLoop(
      border,
      new THREE.LineBasicMaterial({ color: '#7b8c79', transparent: true, opacity: 0.5 }),
    );
    this.scene.add(this.frame);
    // A tiny fixed near plane destroys depth precision on kilometre-scale, nearly flat DSMs.
    this.camera.near = Math.max(0.02, extent / 1000);
    this.camera.far = extent * 40;
    this.camera.updateProjectionMatrix();
    this.orbit.maxDistance = extent * 12;
    this.orbit.minDistance = extent * 0.015;
    this.reset();
  }
  setMesh(mesh: MeshData) {
    this.meshData = mesh;
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(mesh.positions, 3));
    geometry.setAttribute('normal', new THREE.BufferAttribute(mesh.normals, 3));
    geometry.setAttribute('uv', new THREE.BufferAttribute(mesh.uvs, 2));
    geometry.setAttribute('slope', new THREE.BufferAttribute(mesh.slopes, 1));
    geometry.setAttribute('errorValue', new THREE.BufferAttribute(mesh.errors, 1));
    geometry.setAttribute('errorValid', new THREE.BufferAttribute(mesh.errorValid, 1));
    geometry.setIndex(new THREE.BufferAttribute(mesh.indices, 1));
    geometry.computeBoundingBox();
    geometry.computeBoundingSphere();
    if (this.terrain) {
      this.terrain.geometry.dispose();
      this.terrain.geometry = geometry;
      this.terrain.material.uniforms.ortho.value = this.texture;
      this.terrain.material.uniforms.heightRange.value = mesh.max - mesh.min;
    } else {
      const material = new THREE.ShaderMaterial({
        vertexShader,
        fragmentShader,
        uniforms: {
          ortho: { value: this.texture },
          mode: { value: 0 },
          heightRange: { value: mesh.max - mesh.min },
          errorRange: { value: 10 },
          contourStep: { value: 50 },
          contours: { value: false },
          hillshade: { value: true },
          lightDir: { value: this.worldLight.clone() },
        },
      });
      this.terrain = new THREE.Mesh(geometry, material);
      this.group.add(this.terrain);
    }
    if (this.skirt) {
      this.group.remove(this.skirt);
      this.skirt.geometry.dispose();
      (this.skirt.material as THREE.Material).dispose();
    }
    const edge: number[] = [];
    for (let c = 0; c < mesh.cols; c++) edge.push(c);
    for (let r = 1; r < mesh.rows; r++) edge.push(r * mesh.cols + mesh.cols - 1);
    for (let c = mesh.cols - 2; c >= 0; c--) edge.push((mesh.rows - 1) * mesh.cols + c);
    for (let r = mesh.rows - 2; r > 0; r--) edge.push(r * mesh.cols);
    const sides: number[] = [];
    for (let i = 0; i < edge.length; i++) {
      const a = edge[i],
        b = edge[(i + 1) % edge.length];
      if (!mesh.valid[a] || !mesh.valid[b]) continue;
      const ax = mesh.positions[a * 3],
        ay = mesh.positions[a * 3 + 1],
        az = mesh.positions[a * 3 + 2],
        bx = mesh.positions[b * 3],
        by = mesh.positions[b * 3 + 1],
        bz = mesh.positions[b * 3 + 2];
      sides.push(ax, ay, az, ax, 0, az, bx, by, bz, bx, by, bz, ax, 0, az, bx, 0, bz);
    }
    const skirtGeometry = new THREE.BufferGeometry();
    skirtGeometry.setAttribute('position', new THREE.Float32BufferAttribute(sides, 3));
    skirtGeometry.computeVertexNormals();
    this.skirt = new THREE.Mesh(
      skirtGeometry,
      new THREE.MeshStandardMaterial({ color: '#3e4937', roughness: 1, side: THREE.DoubleSide }),
    );
    this.group.add(this.skirt);
  }
  setSurface(mode: Surface, errorRange = 10) {
    if (this.terrain) {
      this.terrain.material.uniforms.mode.value = ['ortho', 'elevation', 'slope', 'error'].indexOf(
        mode,
      );
      this.terrain.material.uniforms.errorRange.value = Math.max(0.001, errorRange);
    }
  }
  setContours(enabled: boolean) {
    if (this.terrain) this.terrain.material.uniforms.contours.value = enabled;
  }
  setHillshade(enabled: boolean) {
    if (this.terrain) this.terrain.material.uniforms.hillshade.value = enabled;
  }
  setExaggeration(value: number) {
    this.exaggeration = value;
    this.group.scale.y = value * this.baseScale;
    this.keepMarkersRound();
  }
  // DepthWizard patch: markers sit inside the vertically scaled group; undo that scale on
  // them so they stay spheres even at the large relative-mode scale.
  private keepMarkersRound() {
    const inverse = 1 / this.group.scale.y;
    for (const child of [this.marker, ...this.profileGroup.children])
      if (child instanceof THREE.Mesh) child.scale.y = inverse;
  }
  setMode(mode: 'orbit' | 'fly') {
    if (this.mode === mode) return;
    this.mode = mode;
    this.orbit.enabled = mode === 'orbit';
    if (mode === 'orbit') {
      this.fly.unlock();
      this.keys.clear();
      const direction = this.camera.getWorldDirection(new THREE.Vector3());
      this.orbit.target.copy(this.camera.position).addScaledVector(direction, this.extent() * 0.5);
      this.orbit.update();
    }
  }
  setDrawing(value: boolean) {
    this.drawing = value;
    this.orbit.enabled = !value && this.mode === 'orbit';
    this.renderer.domElement.style.cursor = value ? 'crosshair' : '';
  }
  private extent() {
    return this.meta
      ? Math.max(this.meta.width - 1, this.meta.height - 1) * this.meta.pixel_size_m
      : 2000;
  }
  reset(top = false) {
    if (!this.meta) return;
    const s = this.extent(),
      h = (this.meta.max_h - this.meta.min_h) * this.exaggeration * this.baseScale * 0.15;
    this.orbit.target.set(0, h, 0);
    this.camera.position.set(
      top ? 0 : s * 0.9,
      h + s * (top ? 1.75 : 0.94),
      top ? 0.001 : s * 1.02,
    );
    this.camera.lookAt(this.orbit.target);
    this.orbit.update();
  }
  zoom(factor: number) {
    if (this.mode === 'orbit') {
      this.camera.position.sub(this.orbit.target).multiplyScalar(factor).add(this.orbit.target);
      this.orbit.update();
    }
  }
  private pick(click: boolean) {
    if (!this.terrain || !this.meta || !this.meshData) return;
    this.raycaster.setFromCamera(
      this.fly.isLocked ? new THREE.Vector2() : this.pointer,
      this.camera,
    );
    this.group.updateMatrixWorld(true);
    const ray = this.raycaster.ray
      .clone()
      .applyMatrix4(new THREE.Matrix4().copy(this.terrain.matrixWorld).invert());
    const hit = pickGrid(ray, this.meshData, this.terrain.geometry.boundingBox!);
    if (!hit) {
      this.onPick?.(null, click);
      return;
    }
    const col = Math.max(
      0,
      Math.min(this.meta.width - 1, hit.x / this.meta.pixel_size_m + (this.meta.width - 1) / 2),
    );
    const row = Math.max(
      0,
      Math.min(this.meta.height - 1, hit.z / this.meta.pixel_size_m + (this.meta.height - 1) / 2),
    );
    this.onPick?.({ col, row }, click);
  }
  clearMarker() {
    if (this.marker) {
      this.group.remove(this.marker);
      this.marker.geometry.dispose();
      (this.marker.material as THREE.Material).dispose();
      this.marker = undefined;
    }
  }
  setMarker(p: GridPoint, height: number) {
    this.clearMarker();
    if (!this.meta) return;
    this.marker = new THREE.Mesh(
      new THREE.SphereGeometry(this.extent() * 0.004, 12, 8),
      new THREE.MeshBasicMaterial({ color: '#f2edb3', depthTest: false }),
    );
    this.marker.position.set(
      (p.col - (this.meta.width - 1) / 2) * this.meta.pixel_size_m,
      height - this.meta.min_h,
      (p.row - (this.meta.height - 1) / 2) * this.meta.pixel_size_m,
    );
    this.marker.renderOrder = 10;
    this.marker.scale.y = 1 / this.group.scale.y;
    this.group.add(this.marker);
  }
  clearProfile() {
    for (const child of [...this.profileGroup.children]) {
      this.profileGroup.remove(child);
      const item = child as THREE.Mesh;
      item.geometry?.dispose();
      (item.material as THREE.Material)?.dispose();
    }
  }
  setProfile(points: ProfilePoint[], highlight = -1) {
    this.clearProfile();
    if (!this.meta) return;
    const m = this.meta,
      segments: THREE.Vector3[][] = [];
    let segment: THREE.Vector3[] = [];
    for (const p of points) {
      if (p.height === null) {
        if (segment.length) segments.push(segment);
        segment = [];
      } else
        segment.push(
          new THREE.Vector3(
            (p.col - (m.width - 1) / 2) * m.pixel_size_m,
            p.height - m.min_h + (this.extent() * 0.002) / this.group.scale.y,
            (p.row - (m.height - 1) / 2) * m.pixel_size_m,
          ),
        );
    }
    if (segment.length) segments.push(segment);
    for (const part of segments) {
      const line = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints(part),
        new THREE.LineBasicMaterial({ color: '#e5f2b5', depthTest: false }),
      );
      line.renderOrder = 20;
      this.profileGroup.add(line);
    }
    for (const [i, p] of points.entries())
      if ((i === 0 || i === points.length - 1 || i === highlight) && p.height !== null) {
        const marker = new THREE.Mesh(
          new THREE.SphereGeometry(this.extent() * 0.006, 12, 8),
          new THREE.MeshBasicMaterial({
            color: i === highlight ? '#ffffff' : '#e5f2b5',
            depthTest: false,
          }),
        );
        marker.position.set(
          (p.col - (m.width - 1) / 2) * m.pixel_size_m,
          p.height - m.min_h + (this.extent() * 0.002) / this.group.scale.y,
          (p.row - (m.height - 1) / 2) * m.pixel_size_m,
        );
        marker.renderOrder = 21;
        marker.scale.y = 1 / this.group.scale.y;
        this.profileGroup.add(marker);
      }
  }
  private animate = () => {
    let last = performance.now(),
      statsStart = last,
      frames = 0,
      lastHover = 0;
    const tick = (now: number) => {
      this.frameId = requestAnimationFrame(tick);
      const dt = Math.min((now - last) / 1000, 0.05);
      last = now;
      if (document.hidden) {
        statsStart = now;
        frames = 0;
        return;
      }
      if (this.mode === 'orbit') this.orbit.update();
      if (this.fly.isLocked) {
        const direction = this.camera.getWorldDirection(new THREE.Vector3()),
          right = new THREE.Vector3().crossVectors(direction, this.camera.up).normalize(),
          motion = new THREE.Vector3();
        if (this.keys.has('KeyW')) motion.add(direction);
        if (this.keys.has('KeyS')) motion.sub(direction);
        if (this.keys.has('KeyD')) motion.add(right);
        if (this.keys.has('KeyA')) motion.sub(right);
        if (this.keys.has('KeyE') || this.keys.has('Space')) motion.y++;
        if (this.keys.has('KeyQ')) motion.y--;
        const speed =
          this.extent() *
          0.15 *
          (this.keys.has('ShiftLeft') || this.keys.has('ShiftRight') ? 3 : 1);
        this.camera.position.addScaledVector(motion.normalize(), speed * dt);
        this.hoverDirty = true;
      }
      if (this.terrain) {
        this.terrain.material.uniforms.lightDir.value
          .copy(this.worldLight)
          .transformDirection(this.camera.matrixWorldInverse);
      }
      this.renderer.render(this.scene, this.camera);
      if (this.hoverDirty && now - lastHover > 85) {
        this.pick(false);
        lastHover = now;
        this.hoverDirty = false;
      }
      frames++;
      if (now - statsStart >= 1200) {
        const fps = (frames * 1000) / (now - statsStart);
        this.onPerformance?.(fps, this.renderer.getPixelRatio());
        this.onHeading?.((this.orbit.getAzimuthalAngle() * 180) / Math.PI);
        if (fps < 48) this.slowWindows++;
        else this.slowWindows = 0;
        if (this.slowWindows >= 3 && this.renderer.getPixelRatio() > 0.75) {
          this.renderer.setPixelRatio(Math.max(0.75, this.renderer.getPixelRatio() - 0.25));
          this.resize();
          this.slowWindows = 0;
        }
        statsStart = now;
        frames = 0;
      }
    };
    this.frameId = requestAnimationFrame(tick);
  };
  dispose() {
    cancelAnimationFrame(this.frameId);
    this.resizeObserver.disconnect();
    this.orbit.dispose();
    this.fly.dispose();
    window.removeEventListener('keydown', this.keydown);
    window.removeEventListener('keyup', this.keyup);
    window.removeEventListener('blur', this.blur);
    this.scene.traverse((object) => {
      const mesh = object as THREE.Mesh;
      mesh.geometry?.dispose();
      if (mesh.material) {
        for (const material of Array.isArray(mesh.material) ? mesh.material : [mesh.material])
          material.dispose();
      }
    });
    this.texture?.dispose();
    (this.texture?.image as ImageBitmap)?.close?.();
    this.renderer.dispose();
  }
}
