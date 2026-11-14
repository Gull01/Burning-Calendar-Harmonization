/* Punjab burning calendar: static web app on harmonized MODIS / VIIRS hotspots. */
(() => {
  "use strict";

  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const MONTHS_LONG = ["January", "February", "March", "April", "May", "June", "July", "August",
    "September", "October", "November", "December"];
  const SAT_NAMES = ["Terra", "Aqua", "Suomi NPP", "NOAA-20", "NOAA-21"];
  const SAT_SENSOR = ["MODIS", "MODIS", "VIIRS", "VIIRS", "VIIRS"];
  const SOURCE_TEXT = {
    viirs: "Observed by VIIRS on S-NPP",
    viirs_scaled: "Observed by VIIRS on NOAA-20, scaled to S-NPP",
    modis_aqua: "Reconstructed from MODIS (Aqua and Terra)",
    modis_terra: "Reconstructed from MODIS (Terra only, least certain)",
    none: "No satellite data",
  };
  const COLORS = {
    light: {
      seq: ["#fde6d8", "#f8b896", "#eb6834", "#b8461a", "#6e250a"],
      zero: "#eceeed", nodata: "#d6dad8", neutral: "#e9e8e4",
      div: ["#184f95", "#5598e7", "#cde2fb", "#e9e8e4", "#f8c9c8", "#e34948", "#8f1d1d"],
      label: "#1f2a2e", labelOnDark: "#ffffff",
      modis: "#2a78d6", viirs: "#eb6834", median: "#5b676b", selYear: "#0f6e7a", curYear: "#eb6834",
      observed: "#eb6834", modeled: "#f8b896", accent: "#0f6e7a",
    },
    dark: {
      seq: ["#4a2314", "#8a3a1a", "#d2582a", "#f08a52", "#ffc39a"],
      zero: "#242d30", nodata: "#333c3e", neutral: "#3a4244",
      div: ["#7fb2f0", "#4f8fdc", "#2a4f7c", "#3a4244", "#8a3b3b", "#e05a59", "#ff9b9a"],
      label: "#e7ecea", labelOnDark: "#141a1c",
      modis: "#5598e7", viirs: "#f08a52", median: "#a3aeb0", selYear: "#4fb3bf", curYear: "#f08a52",
      observed: "#f08a52", modeled: "#8a3a1a", accent: "#4fb3bf",
    },
  };

  const S = {
    region: null, regions: [], baseline: "all",
    meta: null, mat: null, nC: 0, nM: 0, y0: 0, m0: 0,
    sel: null, selList: null, selName: "Whole region", selShape: null, whole: true,
    yearFrom: 0, yearTo: 0, mapMonth: 0, layer: "grid", calView: "count",
    det: new Map(), detLoading: new Map(), series: null, table: null, cellKey: new Map(),
    playing: null, gridMax: 1,
  };

  const $ = (id) => document.getElementById(id);
  const fmt = d3.format(",.0f");
  const fmt1 = d3.format(",.1f");
  const theme = () => {
    const t = document.documentElement.dataset.theme;
    if (t) return t;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  };
  const C = () => COLORS[theme()];

  // ------------------------------------------------------------------ time helpers
  const monthOf = (i) => { const t = S.y0 * 12 + S.m0 + i; return { y: Math.floor(t / 12), m: t % 12 }; };
  const indexOf = (y, m) => y * 12 + m - (S.y0 * 12 + S.m0);
  const monthName = (i) => { const { y, m } = monthOf(i); return `${MONTHS[m]} ${y}`; };
  const dataEnd = () => new Date(S.meta.data_end + "T00:00:00Z");
  const daysInMonth = (y, m) => new Date(Date.UTC(y, m + 1, 0)).getUTCDate();
  const epochDay = (y, m, d) => Math.round((Date.UTC(y, m, d) - Date.UTC(2000, 0, 1)) / 86400000);

  function partialInfo() {
    const e = dataEnd();
    const last = monthOf(S.nM - 1);
    const dim = daysInMonth(last.y, last.m);
    if (e.getUTCFullYear() === last.y && e.getUTCMonth() === last.m && e.getUTCDate() < dim) {
      return { idx: S.nM - 1, day: e.getUTCDate(), dim };
    }
    return null;
  }

  // ------------------------------------------------------------------ data
  const dataUrl = (file) => `data/${S.region}/${file}`;
  const cellKm = () => Math.round(S.meta.grid_deg * 111);
  async function load(regionId) {
    const prev = S.region;
    S.region = regionId;
    let meta, buf;
    try {
      [meta, buf] = await Promise.all([
        fetch(dataUrl("meta.json")).then((r) => { if (!r.ok) throw new Error("meta.json " + r.status); return r.json(); }),
        fetch(dataUrl("harmonized.bin")).then((r) => { if (!r.ok) throw new Error("harmonized.bin " + r.status); return r.arrayBuffer(); }),
      ]);
    } catch (err) {
      S.region = prev;
      throw err;
    }
    S.meta = meta;
    S.mat = new Uint16Array(buf);
    S.nC = meta.cells.lat.length;
    S.nM = meta.n_months;
    S.det = new Map();
    S.detLoading = new Map();
    S.cellKey = new Map();
    const [fy, fm] = meta.first_month.split("-").map(Number);
    S.y0 = fy; S.m0 = fm - 1;
    const g = meta.grid_deg;
    for (let c = 0; c < S.nC; c++) {
      const iy = Math.floor((meta.cells.lat[c] + 90) / g);
      const ix = Math.floor((meta.cells.lon[c] + 180) / g);
      S.cellKey.set(iy * 100000 + ix, c);
    }
    // a robust upper end for map colors: 99th percentile of non-zero cell-months
    const sample = [];
    for (let k = 0; k < S.mat.length; k += 7) {
      const v = S.mat[k];
      if (v !== meta.missing && v > 0) sample.push(v / meta.scale);
    }
    sample.sort((a, b) => a - b);
    S.gridMax = sample[Math.floor(sample.length * 0.99)] || 1;
  }

  async function loadYear(y) {
    if (S.det.has(y)) return S.det.get(y);
    if (S.detLoading.has(y)) return S.detLoading.get(y);
    const n = S.meta.det_years[y];
    if (!n) { S.det.set(y, null); return null; }
    const region = S.region;
    const p = fetch(dataUrl(`det_${y}.bin`)).then((r) => {
      if (!r.ok) throw new Error(`det_${y}.bin ${r.status}`);
      return r.arrayBuffer();
    }).then((buf) => {
      // layout 2: positions stored as offsets inside the grid cell, fire power x 10
      const u16 = (k) => new Uint16Array(buf, 2 * k * n, n);
      const latOff = u16(0), lonOff = u16(1), frp10 = u16(2), cell = u16(5);
      const g = S.meta.grid_deg, cl = S.meta.cells.lat, co = S.meta.cells.lon;
      const lat = new Float32Array(n), lon = new Float32Array(n), frp = new Float32Array(n);
      for (let k = 0; k < n; k++) {
        const c = cell[k];
        lat[k] = cl[c] - g / 2 + (latOff[k] / 65535) * g;
        lon[k] = co[c] - g / 2 + (lonOff[k] / 65535) * g;
        frp[k] = frp10[k] / 10;
      }
      const d = {
        n, lat, lon, frp, cell, day: u16(3), time: u16(4),
        plat: new Uint8Array(buf, 12 * n, n), conf: new Uint8Array(buf, 13 * n, n), dn: new Uint8Array(buf, 14 * n, n),
      };
      if (S.region !== region) return null; // the user switched region while this was loading
      S.det.set(y, d);
      S.detLoading.delete(y);
      return d;
    });
    S.detLoading.set(y, p);
    return p;
  }

  // ------------------------------------------------------------------ selection and series
  function setSelection(list, name, shape) {
    if (!list.length) {
      flash("No fire cells inside that shape. Try a larger area.");
      if (shape) S.map.removeLayer(shape);
      return;
    }
    if (S.selShape && S.selShape !== shape) S.map.removeLayer(S.selShape);
    S.selShape = shape || null;
    S.whole = list.length === S.nC;
    S.sel = new Uint8Array(S.nC);
    list.forEach((c) => { S.sel[c] = 1; });
    S.selList = Int32Array.from(list);
    S.selName = name;
    computeSeries();
    renderAll();
  }

  function selectWhole() {
    const all = Array.from({ length: S.nC }, (_, i) => i);
    setSelection(all, "Whole region", null);
  }

  function computeSeries() {
    const { mat, nM } = S;
    const miss = S.meta.missing, scale = S.meta.scale;
    const out = new Float64Array(nM).fill(NaN);
    for (let i = 0; i < nM; i++) {
      if (S.meta.month_source[i] === "none") continue;
      let sum = 0, any = false;
      for (const c of S.selList) {
        const v = mat[c * nM + i];
        if (v !== miss) { sum += v; any = true; }
      }
      if (any) out[i] = sum / scale;
    }
    S.series = out;
    S.table = buildTable(out);
  }

  function expectedShare(pi) {
    const naive = pi.day / pi.dim;
    const p = S.meta.partial;
    if (!p) return naive;
    const ny = p.years.length;
    const by = new Float64Array(ny), tot = new Float64Array(ny);
    for (const c of S.selList) {
      const b = p.by_day[c], t = p.total[c];
      if (!t) continue;
      for (let k = 0; k < ny; k++) { by[k] += b[k]; tot[k] += t[k]; }
    }
    const shares = [];
    for (let k = 0; k < ny; k++) if (tot[k] >= 20) shares.push(by[k] / tot[k]);
    return shares.length >= 3 ? d3.median(shares) : naive;
  }

  function buildTable(series) {
    const pi = partialInfo();
    const share = pi ? expectedShare(pi) : 1;
    const byMonth = Array.from({ length: 12 }, () => []);   // all years: for ranks
    const baseMonth = Array.from({ length: 12 }, () => []); // comparison window: for "usual"
    const lastFull = monthOf(S.nM - 1).y - 1;
    const fromYear = S.baseline === "all" ? -Infinity : lastFull - Number(S.baseline) + 1;
    for (let i = 0; i < S.nM; i++) {
      if (Number.isNaN(series[i]) || (pi && i === pi.idx)) continue;
      const { y, m } = monthOf(i);
      byMonth[m].push(series[i]);
      if (y >= fromYear) baseMonth[m].push(series[i]);
    }
    const med = baseMonth.map((v) => (v.length ? d3.median(v) : NaN));
    const rows = [];
    for (let i = 0; i < S.nM; i++) {
      const v = series[i];
      if (Number.isNaN(v)) continue;
      const { y, m } = monthOf(i);
      const partial = pi && i === pi.idx;
      const f = partial ? share : 1;
      const usual = med[m] * f;
      const anom = usual >= 10 ? (v / usual - 1) * 100 : null;
      const others = byMonth[m];
      const rank = 1 + others.filter((o) => o * f > v).length;
      rows[i] = {
        i, y, m, v, usual, anom, rank, nYears: others.length + (partial ? 1 : 0), partial: !!partial,
        share: f, day: partial ? pi.day : null, source: S.meta.month_source[i],
      };
    }
    return { rows, med, share, pi };
  }

  // ------------------------------------------------------------------ map
  const CanvasLayer = L.Layer.extend({
    onAdd(map) {
      this._map = map;
      this._c = L.DomUtil.create("canvas", "data-canvas");
      this._c.style.pointerEvents = "none";
      map.getPanes().overlayPane.appendChild(this._c);
      map.on("moveend zoomend resize viewreset", this._reset, this);
      map.on("zoomstart", this._hide, this);
      this._reset();
    },
    onRemove(map) {
      L.DomUtil.remove(this._c);
      map.off("moveend zoomend resize viewreset", this._reset, this);
      map.off("zoomstart", this._hide, this);
    },
    _hide() { this._c.style.visibility = "hidden"; },
    _reset() {
      const map = this._map, size = map.getSize(), dpr = window.devicePixelRatio || 1;
      L.DomUtil.setPosition(this._c, map.containerPointToLayerPoint([0, 0]));
      this._c.width = size.x * dpr; this._c.height = size.y * dpr;
      this._c.style.width = size.x + "px"; this._c.style.height = size.y + "px";
      this._c.style.visibility = "visible";
      const ctx = this._c.getContext("2d");
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, size.x, size.y);
      if (this.draw) this.draw(ctx, map);
    },
    redraw() { if (this._map) this._reset(); },
  });

  // Basemaps that need no API key. Labels sit in their own pane above the fire layer.
  const ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services";
  const ESRI_ATTR = 'Tiles &copy; <a href="https://www.esri.com">Esri</a> and its data providers';
  const OSM_ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
  function esri(path, extra = {}) {
    return L.tileLayer(`${ESRI}/${path}/MapServer/tile/{z}/{y}/{x}`, { maxNativeZoom: 16, maxZoom: 18, attribution: ESRI_ATTR, ...extra });
  }
  function makeBasemaps() {
    const dark = theme() === "dark";
    const gray = dark ? "Dark_Gray" : "Light_Gray";
    const labelOpts = { pane: "labels", attribution: "" };
    return {
      "Light gray": L.layerGroup([esri(`Canvas/World_${gray}_Base`), esri(`Canvas/World_${gray}_Reference`, labelOpts)]),
      "Streets": L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, attribution: OSM_ATTR }),
      "Satellite": L.layerGroup([
        esri("World_Imagery", { maxNativeZoom: 17, attribution: `${ESRI_ATTR}, Maxar, Earthstar Geographics` }),
        esri("Reference/World_Boundaries_and_Places", labelOpts),
      ]),
    };
  }
  const BASE_THUMBS = {
    "Light gray": () => (theme() === "dark" ? "linear-gradient(135deg,#2b3134,#3a4144)" : "linear-gradient(135deg,#f1f1ef,#dcdcd8)"),
    "Streets": () => "linear-gradient(135deg,#f2efe9 0 55%,#aad3df 55% 70%,#f2efe9 70%)",
    "Satellite": () => "linear-gradient(135deg,#55613a,#8a7a4c 55%,#3d4a2c)",
  };
  let basemaps = null, currentBase = "Light gray";
  function setTiles() {
    if (basemaps) Object.values(basemaps).forEach((l) => S.map.removeLayer(l));
    basemaps = makeBasemaps();
    basemaps[currentBase].addTo(S.map);
    const pop = $("basemapPop");
    pop.innerHTML = Object.keys(basemaps).map((name) =>
      `<button type="button" class="bm" role="radio" aria-checked="${name === currentBase}" data-base="${name}">` +
      `<span class="thumb" style="background:${BASE_THUMBS[name]()}"></span>${name}</button>`).join("");
    pop.querySelectorAll(".bm").forEach((b) => b.addEventListener("click", () => {
      currentBase = b.dataset.base;
      setTiles();
      closePops();
    }));
  }

  // ------------------------------------------------------------------ popovers and panel
  function closePops(except) {
    [["coordsBtn", "coordsPop"], ["basemapBtn", "basemapPop"]].forEach(([b, p]) => {
      if (b === except) return;
      $(p).hidden = true;
      $(b).setAttribute("aria-expanded", "false");
    });
  }
  function initPops() {
    [["coordsBtn", "coordsPop"], ["basemapBtn", "basemapPop"]].forEach(([b, p]) => {
      $(b).addEventListener("click", (e) => {
        e.stopPropagation();
        const open = $(p).hidden;
        closePops(b);
        $(p).hidden = !open;
        $(b).setAttribute("aria-expanded", String(open));
        if (open && b === "coordsBtn") $("inLat").focus();
      });
      $(p).addEventListener("click", (e) => e.stopPropagation());
    });
    document.addEventListener("click", () => closePops());
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") closePops(); });
  }
  const isPhone = () => window.matchMedia("(max-width: 760px)").matches;
  function setPanel(open) {
    $("app").classList.toggle("panel-open", open);
    if (open) {
      setTimeout(() => { renderCalendar(); renderSeason(); renderAnnual(); }, 30);
      $("panelClose").focus({ preventScroll: true });
    } else {
      $("panelOpen").focus({ preventScroll: true });
    }
  }
  function fitRegion() {
    const [x0, y0, x1, y1] = S.meta.bbox;
    const right = !isPhone() && $("app").classList.contains("panel-open") ? $("panel").offsetWidth + 32 : 0;
    const left = isPhone() ? 0 : 60;
    const top = isPhone() ? $("brand").offsetHeight + 10 : 20;
    S.map.fitBounds([[y0, x0], [y1, x1]], { paddingTopLeft: [left, top], paddingBottomRight: [right, 100] });
  }

  function cellAnom(c, i, v) {
    const { m } = monthOf(i);
    const vals = [];
    const pi = S.table.pi;
    for (let k = (m - S.m0 + 12) % 12; k < S.nM; k += 12) {
      if (pi && k === pi.idx) continue;
      const x = S.mat[c * S.nM + k];
      if (x !== S.meta.missing) vals.push(x / S.meta.scale);
    }
    const med = d3.median(vals) || 0;
    const f = pi && i === pi.idx ? S.table.share : 1;
    return { med: med * f, ratio: Math.log2((v + 0.5) / (med * f + 0.5)) };
  }

  function drawMap(ctx, map) {
    const g = S.meta.grid_deg / 2;
    const i = S.mapMonth, nM = S.nM, miss = S.meta.missing, scale = S.meta.scale;
    const cl = C();
    const lat = S.meta.cells.lat, lon = S.meta.cells.lon;
    const bounds = map.getBounds().pad(0.05);
    S.drawn = [];
    if (S.layer === "grid" || S.layer === "anom") {
      const seq = d3.scaleSequentialSqrt(d3.interpolateRgbBasis(cl.seq)).domain([0, S.gridMax]).clamp(true);
      const div = d3.scaleLinear().domain([-2, -1.33, -0.67, 0, 0.67, 1.33, 2]).range(cl.div).clamp(true);
      ctx.globalAlpha = 0.86;
      for (let c = 0; c < S.nC; c++) {
        if (!bounds.contains([lat[c], lon[c]])) continue;
        const raw = S.mat[c * nM + i];
        if (raw === miss) continue;
        const v = raw / scale;
        let fill;
        if (S.layer === "grid") {
          if (v < 0.05) continue;
          fill = seq(v);
        } else {
          const a = cellAnom(c, i, v);
          if (v < 0.05 && a.med < 0.05) continue;
          fill = div(a.ratio);
        }
        const p1 = map.latLngToContainerPoint([lat[c] + g, lon[c] - g]);
        const p2 = map.latLngToContainerPoint([lat[c] - g, lon[c] + g]);
        ctx.fillStyle = fill;
        ctx.fillRect(p1.x, p1.y, Math.max(1, p2.x - p1.x - 0.5), Math.max(1, p2.y - p1.y - 0.5));
      }
      ctx.globalAlpha = 1;
    } else {
      const { y, m } = monthOf(i);
      const d = S.det.get(y);
      if (d) {
        const a = epochDay(y, m, 1), b = epochDay(y, m + 1, 1);
        // VIIRS first, MODIS on top so the rarer MODIS points stay visible
        for (const pass of [1, 0]) {
          ctx.fillStyle = pass ? cl.viirs : cl.modis;
          for (let k = 0; k < d.n; k++) {
            if (d.day[k] < a || d.day[k] >= b) continue;
            const isModis = d.plat[k] < 2;
            if (pass === 1 && isModis) continue;
            if (pass === 0 && !isModis) continue;
            const p = map.latLngToContainerPoint([d.lat[k], d.lon[k]]);
            ctx.fillRect(p.x - 1.5, p.y - 1.5, 3, 3);
            S.drawn.push(k, p.x, p.y);
          }
        }
      } else {
        loadYear(y).then(() => S.overlay.redraw()).catch(showError);
      }
    }
    // selection outline
    if (!S.whole && S.selList) {
      ctx.strokeStyle = cl.accent;
      ctx.lineWidth = 1;
      for (const c of S.selList) {
        const p1 = map.latLngToContainerPoint([lat[c] + g, lon[c] - g]);
        const p2 = map.latLngToContainerPoint([lat[c] - g, lon[c] + g]);
        ctx.strokeRect(p1.x + 0.5, p1.y + 0.5, p2.x - p1.x - 1, p2.y - p1.y - 1);
      }
    }
  }

  function initMap() {
    if (isPhone()) $("app").classList.remove("panel-open");
    const brand = $("brand");
    const setBrandH = () => document.documentElement.style.setProperty("--brand-h", brand.offsetHeight + "px");
    setBrandH();
    if (window.ResizeObserver) new ResizeObserver(setBrandH).observe(brand);
    S.map = L.map("map", { zoomSnap: 0.5, preferCanvas: true, attributionControl: false, zoomControl: false });
    L.control.zoom({ position: "topleft" }).addTo(S.map);
    L.control.attribution({ position: "bottomleft" }).addTo(S.map);
    fitRegion();
    const labels = S.map.createPane("labels");
    labels.style.zIndex = 450; // above the fire layer (overlay pane, 400), below markers and popups
    labels.style.pointerEvents = "none";
    setTiles();
    S.overlay = new CanvasLayer();
    S.overlay.draw = drawMap;
    S.overlay.addTo(S.map);

    const shape = { color: COLORS.light.accent, weight: 2, dashArray: "5 4", fill: false };
    const drawCtl = new L.Control.Draw({
      position: "topleft",
      draw: {
        polyline: false, marker: false, circlemarker: false,
        rectangle: { shapeOptions: shape, showArea: false },
        polygon: { shapeOptions: shape, allowIntersection: false, showArea: false },
        circle: { shapeOptions: shape, showRadius: true, metric: true },
      },
      edit: false,
    });
    L.drawLocal.draw.toolbar.buttons.rectangle = "Select a rectangle";
    L.drawLocal.draw.toolbar.buttons.polygon = "Select an area by drawing its outline";
    L.drawLocal.draw.toolbar.buttons.circle = "Select a circle around a point";
    S.map.addControl(drawCtl);
    S.map.on(L.Draw.Event.CREATED, (e) => selectByLayer(e.layer, e.layerType));

    S.map.on("mousemove", (e) => onMapHover(e));
    S.map.on("mouseout", hideTip);
  }

  function selectByLayer(layer, type) {
    layer.addTo(S.map);
    const lat = S.meta.cells.lat, lon = S.meta.cells.lon;
    const list = [];
    let name = "Drawn area";
    if (type === "circle") {
      const ctr = layer.getLatLng(), r = layer.getRadius();
      for (let c = 0; c < S.nC; c++) if (S.map.distance(ctr, [lat[c], lon[c]]) <= r) list.push(c);
      name = `${fmt(r / 1000)} km around ${ctr.lat.toFixed(2)} N, ${ctr.lng.toFixed(2)} E`;
    } else {
      const ring = layer.getLatLngs()[0].map((p) => [p.lng, p.lat]);
      for (let c = 0; c < S.nC; c++) if (pointInPolygon([lon[c], lat[c]], ring)) list.push(c);
      name = type === "rectangle" ? "Drawn rectangle" : "Drawn area";
    }
    setSelection(list, name, layer);
  }

  function pointInPolygon(pt, ring) {
    let inside = false;
    for (let a = 0, b = ring.length - 1; a < ring.length; b = a++) {
      const [xa, ya] = ring[a], [xb, yb] = ring[b];
      if ((ya > pt[1]) !== (yb > pt[1]) && pt[0] < ((xb - xa) * (pt[1] - ya)) / (yb - ya) + xa) inside = !inside;
    }
    return inside;
  }

  let hoverRaf = 0;
  function onMapHover(e) {
    cancelAnimationFrame(hoverRaf);
    hoverRaf = requestAnimationFrame(() => {
      const ev = e.originalEvent;
      if (S.layer === "points") {
        const p = e.containerPoint;
        let best = -1, bd = 49;
        for (let q = 0; q < S.drawn.length; q += 3) {
          const dx = S.drawn[q + 1] - p.x, dy = S.drawn[q + 2] - p.y, d2 = dx * dx + dy * dy;
          if (d2 < bd) { bd = d2; best = S.drawn[q]; }
        }
        const d = S.det.get(monthOf(S.mapMonth).y);
        if (best < 0 || !d) return hideTip();
        const date = new Date(Date.UTC(2000, 0, 1) + d.day[best] * 86400000).toISOString().slice(0, 10);
        const t = String(d.time[best]).padStart(4, "0");
        const conf = d.plat[best] < 2 ? `${d.conf[best]}%` : (d.conf[best] >= 100 ? "high" : "nominal");
        showTip(ev, `<strong>${date}</strong>, ${t.slice(0, 2)}:${t.slice(2)} UTC<br>${SAT_NAMES[d.plat[best]]} (${SAT_SENSOR[d.plat[best]]})<br>` +
          `Fire power ${fmt1(d.frp[best])} MW, confidence ${conf}<br>${d.lat[best].toFixed(4)}, ${d.lon[best].toFixed(4)}`);
        return;
      }
      const g = S.meta.grid_deg;
      const key = Math.floor((e.latlng.lat + 90) / g) * 100000 + Math.floor((e.latlng.lng + 180) / g);
      const c = S.cellKey.get(key);
      if (c === undefined) return hideTip();
      const raw = S.mat[c * S.nM + S.mapMonth];
      if (raw === S.meta.missing) return hideTip();
      const v = raw / S.meta.scale;
      const a = cellAnom(c, S.mapMonth, v);
      showTip(ev, `<strong>${monthName(S.mapMonth)}</strong><br>${fmt1(v)} hotspots in this cell<br>` +
        `Usual for this month: ${fmt1(a.med)}<br><span class="muted">Cell centre ${S.meta.cells.lat[c].toFixed(2)} N, ${S.meta.cells.lon[c].toFixed(2)} E</span>`);
    });
  }

  function mapLegend() {
    const cl = C();
    const el = $("mapLegend");
    if (S.layer === "grid") {
      el.innerHTML = `<span>Hotspots per cell in the month</span><span>0<span class="ramp" style="background:linear-gradient(90deg,${cl.seq.join(",")})"></span>${fmt(S.gridMax)}+</span><span>Cells are about ${cellKm()} km across</span>`;
    } else if (S.layer === "anom") {
      el.innerHTML = `<span>Each cell compared with its own usual for this month</span><span>4x fewer<span class="ramp" style="background:linear-gradient(90deg,${cl.div.join(",")})"></span>4x more</span>`;
    } else {
      el.innerHTML = `<span><span class="sw" style="background:${cl.modis}"></span>MODIS (1 km)</span><span><span class="sw" style="background:${cl.viirs}"></span>VIIRS (375 m)</span><span>Every satellite detection in the month, before harmonization</span>`;
    }
  }

  // ------------------------------------------------------------------ tooltip and messages
  const tip = $("tip");
  function showTip(ev, html) {
    tip.innerHTML = html;
    tip.hidden = false;
    const pad = 14, w = tip.offsetWidth, h = tip.offsetHeight;
    let x = ev.clientX + pad, y = ev.clientY + pad;
    if (x + w > window.innerWidth - 8) x = ev.clientX - w - pad;
    if (y + h > window.innerHeight - 8) y = ev.clientY - h - pad;
    tip.style.left = Math.max(8, x) + "px";
    tip.style.top = Math.max(8, y) + "px";
  }
  function hideTip() { tip.hidden = true; }
  function flash(msg) { $("selInfo").textContent = msg; }
  function showError(err) {
    console.error(err);
    $("nowText").textContent = `The data could not be loaded (${err.message}). Check that the data folder was deployed with the site, then reload.`;
  }

  // ------------------------------------------------------------------ rendering
  function renderAll() {
    renderSelInfo();
    renderNow();
    renderCalendar();
    renderSeason();
    renderAnnual();
    renderFacts();
    mapLegend();
    S.overlay.redraw();
  }

  function renderSelInfo() {
    $("selName").textContent = S.selName;
    const n = S.selList.length;
    const midLat = d3.mean(S.selList, (c) => S.meta.cells.lat[c]);
    const km = S.meta.grid_deg * 111.32;
    const area = n * km * km * Math.cos((midLat * Math.PI) / 180);
    $("selInfo").textContent = `${fmt(n)} grid cell${n === 1 ? "" : "s"}, about ${fmt(Math.round(area / 100) * 100)} square km` +
      (S.whole ? ". Draw on the map or use the pin button to pick an area." : "");
    $("resetSel").hidden = S.whole;
  }

  function renderNow() {
    const r = S.table.rows[S.nM - 1];
    if (!r) { $("nowValue").textContent = "n/a"; $("nowText").textContent = "No data for the latest month."; return; }
    $("nowValue").textContent = fmt(r.v);
    const when = r.partial ? `${MONTHS_LONG[r.m]} ${r.y} so far (first ${r.day} days)` : `${MONTHS_LONG[r.m]} ${r.y}`;
    $("nowUnit").textContent = `Hotspots in ${when}`;
    let txt;
    if (r.anom === null) {
      txt = `Too few fires usually happen at this time of year for a fair comparison (usual: about ${fmt(r.usual)}).`;
    } else {
      const dir = r.anom >= 0 ? "above" : "below";
      const span = S.baseline === "all" ? "" : ` of the last ${S.baseline} years`;
      const typical = r.partial ? `the typical level${span} by this date (about ${fmt(r.usual)}, since ${Math.round(r.share * 100)}% of a usual ${MONTHS_LONG[r.m]}'s fires have happened by day ${r.day})`
        : `the usual ${MONTHS_LONG[r.m]}${span} (${fmt(r.usual)})`;
      txt = `${fmt(Math.abs(r.anom))}% ${dir} ${typical}. ${r.rank === 1 ? "The highest" : `The ${ordinal(r.rank)} highest`} of ${r.nYears} years.`;
    }
    $("nowText").textContent = txt + ` ${SOURCE_TEXT[r.source]}.`;
    $("regionNote").textContent = S.meta.note || "";
    $("regionNote").hidden = !S.meta.note;
  }

  function ordinal(n) {
    const s = ["th", "st", "nd", "rd"], v = n % 100;
    return n + (s[(v - 20) % 10] || s[v] || s[0]);
  }

  function calColor(r) {
    const cl = C();
    if (!r) return cl.nodata;
    if (S.calView === "count") {
      if (r.v < 0.5) return cl.zero;
      return S.calSeq(r.v);
    }
    if (r.anom === null) return cl.neutral;
    const ratio = Math.log2(Math.min(4, Math.max(0.25, 1 + r.anom / 100)));
    return d3.scaleLinear().domain([-2, -1.33, -0.67, 0, 0.67, 1.33, 2]).range(cl.div)(ratio);
  }

  function rowTip(r) {
    if (!r) return "No satellite data";
    let s = `<strong>${MONTHS_LONG[r.m]} ${r.y}</strong>${r.partial ? ` (first ${r.day} days)` : ""}<br>${fmt(r.v)} hotspots<br>`;
    s += `Usual${r.partial ? " by this date" : ""}: ${fmt(r.usual)}`;
    if (r.anom !== null) s += `, ${fmt(Math.abs(r.anom))}% ${r.anom >= 0 ? "above" : "below"}`;
    s += `<br>Rank ${r.rank} of ${r.nYears} ${MONTHS_LONG[r.m]}s<br><span class="muted">${SOURCE_TEXT[r.source]}</span>`;
    return s;
  }

  function renderCalendar() {
    const el = $("calendar");
    const cl = C();
    const W = Math.max(300, el.clientWidth || 480);
    const years = d3.range(S.yearFrom, S.yearTo + 1);
    const left = 46, top = 18, gap = 2;
    const cw = (W - left) / 12;
    const ch = Math.max(14, Math.min(22, cw * 0.55));
    const H = top + years.length * ch + 2;
    const rows = S.table.rows;
    const vis = [];
    years.forEach((y) => { for (let m = 0; m < 12; m++) { const r = rows[indexOf(y, m)]; if (r) vis.push(r.v); } });
    vis.sort((a, b) => a - b);
    const hi = vis.length ? vis[Math.floor((vis.length - 1) * 0.99)] : 1;
    S.calSeq = d3.scaleSequential(d3.interpolateRgbBasis(cl.seq)).domain([0, Math.max(1, hi)]).clamp(true);

    const svg = d3.create("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("role", "img")
      .attr("aria-label", `Burning calendar for ${S.selName}, ${S.yearFrom} to ${S.yearTo}, one square per month`);
    svg.append("g").selectAll("text").data(MONTHS).join("text")
      .attr("x", (_, m) => left + m * cw + cw / 2).attr("y", 12).attr("text-anchor", "middle").text((d) => d);
    const g = svg.append("g").attr("transform", `translate(0,${top})`);
    years.forEach((y, yi) => {
      const modeled = d3.range(12).filter((m) => { const r = rows[indexOf(y, m)]; return r && r.source.startsWith("modis"); }).length > 6;
      g.append("text").attr("x", left - 8).attr("y", yi * ch + ch / 2 + 4).attr("text-anchor", "end")
        .text(modeled ? `${y}*` : y);
      let peak = null;
      for (let m = 0; m < 12; m++) {
        const i = indexOf(y, m);
        const r = i >= 0 && i < S.nM ? rows[i] : null;
        const rect = g.append("rect").attr("class", "cal-cell")
          .attr("x", left + m * cw + gap / 2).attr("y", yi * ch + gap / 2)
          .attr("width", cw - gap).attr("height", ch - gap).attr("rx", 2.5)
          .attr("fill", calColor(r));
        if (r && r.partial) rect.attr("stroke", cl.median).attr("stroke-dasharray", "2 2").attr("stroke-width", 1);
        if (i === S.mapMonth) rect.attr("stroke", cl.accent).attr("stroke-width", 2.5).attr("stroke-dasharray", null);
        rect.on("mousemove", (ev) => showTip(ev, rowTip(r))).on("mouseleave", hideTip)
          .on("click", () => { if (r) setMapMonth(i); });
        if (r && S.calView === "count" && (!peak || r.v > peak.r.v)) peak = { r, m };
      }
      if (peak && cw >= 30 && peak.r.v >= 1) {
        const dark = S.calSeq(peak.r.v);
        const lum = d3.lab(dark).l;
        g.append("text").attr("x", left + peak.m * cw + cw / 2).attr("y", yi * ch + ch / 2 + 3.5)
          .attr("text-anchor", "middle").attr("font-size", 9.5).attr("pointer-events", "none")
          .style("fill", lum < 55 ? "#ffffff" : "#1f2a2e")
          .text(peak.r.v >= 10000 && cw < 44 ? d3.format(".3~s")(peak.r.v) : fmt(peak.r.v));
      }
    });
    el.replaceChildren(svg.node());

    const leg = $("calLegend");
    if (S.calView === "count") {
      leg.innerHTML = `<span>Hotspots per month</span><span>0<span class="ramp" style="background:linear-gradient(90deg,${cl.seq.join(",")})"></span>${fmt(hi)}+</span>` +
        `<span><span class="sw" style="background:${cl.nodata}"></span>No data</span><span>* reconstructed from MODIS</span>`;
    } else {
      leg.innerHTML = `<span>Compared with the usual for that month</span><span>4x fewer<span class="ramp" style="background:linear-gradient(90deg,${cl.div.join(",")})"></span>4x more</span>` +
        `<span>Gray: usual is under 10, too few to compare</span><span>* reconstructed from MODIS</span>`;
    }
  }

  function renderSeason() {
    const el = $("season");
    const cl = C();
    const W = Math.max(300, el.clientWidth || 480), H = 210;
    const m = { l: 44, r: 12, t: 10, b: 24 };
    const rows = S.table.rows;
    const qs = d3.range(12).map((mo) => {
      const v = [];
      for (let y = S.yearFrom; y <= S.yearTo; y++) { const r = rows[indexOf(y, mo)]; if (r && !r.partial) v.push(r.v); }
      v.sort((a, b) => a - b);
      return { mo, q1: d3.quantileSorted(v, 0.25), med: d3.quantileSorted(v, 0.5), q3: d3.quantileSorted(v, 0.75) };
    });
    const mapYear = monthOf(S.mapMonth).y;
    const curYear = monthOf(S.nM - 1).y;
    const yearLine = (y) => d3.range(12).map((mo) => { const r = rows[indexOf(y, mo)]; return r ? { mo, v: r.v } : null; }).filter(Boolean);
    const lines = [{ y: mapYear, color: cl.selYear, label: `${mapYear} (on the map)` }];
    if (curYear !== mapYear) lines.push({ y: curYear, color: cl.curYear, label: `${curYear}` });
    const allV = qs.map((q) => q.q3 || 0).concat(...lines.map((l) => yearLine(l.y).map((p) => p.v)));
    const x = d3.scalePoint().domain(d3.range(12)).range([m.l, W - m.r]).padding(0.3);
    const yS = d3.scaleLinear().domain([0, d3.max(allV) || 1]).nice().range([H - m.b, m.t]);

    const svg = d3.create("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("role", "img")
      .attr("aria-label", `Seasonal profile for ${S.selName}`);
    svg.append("g").attr("class", "grid").selectAll("line").data(yS.ticks(4)).join("line")
      .attr("x1", m.l).attr("x2", W - m.r).attr("y1", yS).attr("y2", yS);
    svg.append("g").attr("class", "axis").attr("transform", `translate(${m.l},0)`)
      .call(d3.axisLeft(yS).ticks(4).tickFormat(d3.format("~s")).tickSize(0)).call((a) => a.select(".domain").remove());
    svg.append("g").attr("class", "axis").attr("transform", `translate(0,${H - m.b})`)
      .call(d3.axisBottom(x).tickFormat((d) => MONTHS[d]).tickSize(0)).call((a) => a.select(".domain").remove())
      .selectAll("text").attr("dy", "1.1em");
    const band = qs.filter((q) => q.q1 !== undefined);
    svg.append("path").datum(band).attr("fill", cl.seq[1]).attr("opacity", theme() === "dark" ? 0.55 : 0.45)
      .attr("d", d3.area().x((d) => x(d.mo)).y0((d) => yS(d.q1)).y1((d) => yS(d.q3)).curve(d3.curveMonotoneX));
    svg.append("path").datum(band).attr("fill", "none").attr("stroke", cl.median).attr("stroke-width", 1.5)
      .attr("stroke-dasharray", "4 3").attr("d", d3.line().x((d) => x(d.mo)).y((d) => yS(d.med)).curve(d3.curveMonotoneX));
    lines.forEach((l) => {
      const pts = yearLine(l.y);
      svg.append("path").datum(pts).attr("fill", "none").attr("stroke", l.color).attr("stroke-width", 2)
        .attr("d", d3.line().x((d) => x(d.mo)).y((d) => yS(d.v)).curve(d3.curveMonotoneX));
      svg.append("g").selectAll("circle").data(pts).join("circle").attr("cx", (d) => x(d.mo)).attr("cy", (d) => yS(d.v))
        .attr("r", 3).attr("fill", l.color).attr("stroke", "var(--panel)").attr("stroke-width", 1.5);
    });
    // hover columns
    const cross = svg.append("line").attr("stroke", cl.median).attr("stroke-width", 1).attr("y1", m.t).attr("y2", H - m.b).attr("opacity", 0);
    const step = x.step();
    svg.append("g").selectAll("rect").data(d3.range(12)).join("rect")
      .attr("x", (d) => x(d) - step / 2).attr("y", m.t).attr("width", step).attr("height", H - m.t - m.b).attr("fill", "transparent")
      .on("mousemove", (ev, mo) => {
        cross.attr("x1", x(mo)).attr("x2", x(mo)).attr("opacity", 0.6);
        const q = qs[mo];
        let s = `<strong>${MONTHS_LONG[mo]}</strong><br>Usual: ${q.med !== undefined ? fmt(q.med) : "n/a"}`;
        if (q.q1 !== undefined) s += ` (middle half ${fmt(q.q1)} to ${fmt(q.q3)})`;
        lines.forEach((l) => { const r = rows[indexOf(l.y, mo)]; s += `<br>${l.y}: ${r ? fmt(r.v) + (r.partial ? " so far" : "") : "n/a"}`; });
        showTip(ev, s);
      })
      .on("mouseleave", () => { cross.attr("opacity", 0); hideTip(); });
    const legend = document.createElement("div");
    legend.className = "legend";
    legend.innerHTML = `<span><span class="ln" style="border-color:${cl.median};border-top-style:dashed"></span>Usual (median)</span>` +
      `<span><span class="sw" style="background:${cl.seq[1]};opacity:.6"></span>Middle half of years</span>` +
      lines.map((l) => `<span><span class="ln" style="border-color:${l.color}"></span>${l.label}</span>`).join("");
    el.replaceChildren(svg.node(), legend);
  }

  function renderAnnual() {
    const el = $("annual");
    const cl = C();
    const W = Math.max(300, el.clientWidth || 480), H = 190;
    const m = { l: 44, r: 8, t: 10, b: 24 };
    const rows = S.table.rows;
    const data = d3.range(S.yearFrom, S.yearTo + 1).map((y) => {
      const rs = d3.range(12).map((mo) => rows[indexOf(y, mo)]).filter(Boolean);
      const complete = rs.length === 12 && !rs.some((r) => r.partial);
      const modeled = rs.filter((r) => r.source.startsWith("modis")).length > rs.length / 2;
      return { y, v: d3.sum(rs, (r) => r.v), n: rs.length, complete, modeled };
    }).filter((d) => d.n > 0);
    const x = d3.scaleBand().domain(data.map((d) => d.y)).range([m.l, W - m.r]).padding(0.18);
    const yS = d3.scaleLinear().domain([0, d3.max(data, (d) => d.v) || 1]).nice().range([H - m.b, m.t]);
    const svg = d3.create("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("role", "img")
      .attr("aria-label", `Hotspots per year for ${S.selName}`);
    svg.append("g").attr("class", "grid").selectAll("line").data(yS.ticks(4)).join("line")
      .attr("x1", m.l).attr("x2", W - m.r).attr("y1", yS).attr("y2", yS);
    svg.append("g").attr("class", "axis").attr("transform", `translate(${m.l},0)`)
      .call(d3.axisLeft(yS).ticks(4).tickFormat(d3.format("~s")).tickSize(0)).call((a) => a.select(".domain").remove());
    const every = Math.ceil(data.length / Math.max(4, Math.floor((W - m.l) / 46)));
    svg.append("g").attr("class", "axis").attr("transform", `translate(0,${H - m.b})`)
      .call(d3.axisBottom(x).tickValues(data.map((d) => d.y).filter((y, k) => k % every === 0)).tickSize(0))
      .call((a) => a.select(".domain").remove()).selectAll("text").attr("dy", "1.1em");
    const bw = x.bandwidth();
    svg.append("g").selectAll("path").data(data).join("path")
      .attr("fill", (d) => (d.modeled ? cl.modeled : cl.observed))
      .attr("opacity", (d) => (d.complete ? 1 : 0.55))
      .attr("d", (d) => {
        const x0 = x(d.y), y0 = yS(d.v), y1 = yS(0), r = Math.min(3, bw / 2, (y1 - y0));
        return `M${x0},${y1}V${y0 + r}Q${x0},${y0} ${x0 + r},${y0}H${x0 + bw - r}Q${x0 + bw},${y0} ${x0 + bw},${y0 + r}V${y1}Z`;
      })
      .on("mousemove", (ev, d) => showTip(ev, `<strong>${d.y}</strong>${d.complete ? "" : " (partial year)"}<br>${fmt(d.v)} hotspots<br><span class="muted">${d.modeled ? "Reconstructed from MODIS" : "Observed by VIIRS"}</span>`))
      .on("mouseleave", hideTip);
    const legend = document.createElement("div");
    legend.className = "legend";
    legend.innerHTML = `<span><span class="sw" style="background:${cl.modeled}"></span>Reconstructed from MODIS</span>` +
      `<span><span class="sw" style="background:${cl.observed}"></span>Observed by VIIRS</span><span>Faded bars: year not complete</span>`;
    el.replaceChildren(svg.node(), legend);
  }

  function renderFacts() {
    const rows = S.table.rows;
    const med = S.table.med;
    const peakM = d3.maxIndex(med);
    const years = d3.range(S.yearFrom, S.yearTo + 1).map((y) => {
      const rs = d3.range(12).map((mo) => rows[indexOf(y, mo)]).filter(Boolean);
      return { y, v: d3.sum(rs, (r) => r.v), complete: rs.length === 12 && !rs.some((r) => r.partial) };
    }).filter((d) => d.complete);
    const top = years.slice().sort((a, b) => b.v - a.v).slice(0, 3);
    const low = years.length ? years.reduce((a, b) => (b.v < a.v ? b : a)) : null;
    let trend = "Not enough complete years in the range";
    if (years.length >= 10) {
      const a = d3.mean(years.slice(0, 5), (d) => d.v), b = d3.mean(years.slice(-5), (d) => d.v);
      const pct = (b / a - 1) * 100;
      trend = `${pct >= 0 ? "+" : ""}${fmt(pct)}% (average of ${years[years.length - 5].y} to ${years[years.length - 1].y} vs ${years[0].y} to ${years[4].y})`;
    }
    const secondM = d3.range(12).filter((mo) => Math.abs(mo - peakM) > 2 && Math.abs(mo - peakM) < 10)
      .reduce((a, mo) => (a === null || med[mo] > med[a] ? mo : a), null);
    const total = d3.sum(d3.range(S.yearFrom, S.yearTo + 1).flatMap((y) => d3.range(12).map((mo) => rows[indexOf(y, mo)])).filter(Boolean), (r) => r.v);
    const items = [
      ["Main burning season", `${MONTHS_LONG[peakM]} (usually about <span class="num">${fmt(med[peakM])}</span> hotspots)` +
        (secondM !== null && med[secondM] > med[peakM] * 0.35 ? `, then ${MONTHS_LONG[secondM]} (${fmt(med[secondM])})` : "")],
      ["Busiest years", top.map((d) => `${d.y} (<span class="num">${fmt(d.v)}</span>)`).join(", ") || "n/a"],
      ["Quietest year", low ? `${low.y} (<span class="num">${fmt(low.v)}</span>)` : "n/a"],
      ["Change over the range", trend],
      [`Total, ${S.yearFrom} to ${S.yearTo}`, `<span class="num">${fmt(total)}</span> hotspots (S-NPP VIIRS equivalent)`],
    ];
    $("facts").innerHTML = items.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("");
  }

  // ------------------------------------------------------------------ controls
  function setMapMonth(i) {
    S.mapMonth = Math.max(0, Math.min(S.nM - 1, i));
    $("monthSlider").value = S.mapMonth;
    const pi = S.table.pi;
    $("monthLabel").textContent = monthName(S.mapMonth) + (pi && pi.idx === S.mapMonth ? ` (to the ${ordinal(pi.day)})` : "");
    $("monthLabel").title = $("monthLabel").textContent;
    $("monthSlider").setAttribute("aria-valuetext", $("monthLabel").textContent);
    if (S.layer === "points") {
      const y = monthOf(S.mapMonth).y;
      if (!S.det.has(y)) loadYear(y).then(() => S.overlay.redraw()).catch(showError);
    }
    S.overlay.redraw();
    renderCalendar();
    renderSeason();
  }

  function setupRegionControls() {
    const lastY = monthOf(S.nM - 1).y;
    const firstFull = S.m0 === 0 ? S.y0 : S.y0 + 1;
    const opts = d3.range(S.y0, lastY + 1).map((y) => `<option value="${y}">${y}</option>`).join("");
    $("yearFrom").innerHTML = opts; $("yearTo").innerHTML = opts;
    S.yearFrom = firstFull; S.yearTo = lastY;
    $("yearFrom").value = S.yearFrom; $("yearTo").value = S.yearTo;
    $("monthSlider").max = S.nM - 1;
    $("dataEnd").textContent = new Date(S.meta.data_end + "T00:00:00Z")
      .toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
    document.title = `${S.meta.region} burning calendar`;
    document.querySelectorAll(".region-name").forEach((el) => { el.textContent = S.meta.short_name || S.meta.region; });
    document.querySelectorAll(".cell-km").forEach((el) => { el.textContent = `${cellKm()} km`; });
    $("methodModel").textContent = (S.meta.method && S.meta.method.model) || "gradient boosting";
  }

  async function switchRegion(id) {
    if (id === S.region) return;
    if (S.playing) $("playBtn").click();
    $("regionSel").disabled = true;
    $("nowText").textContent = "Loading data";
    try {
      await load(id);
      if (S.selShape) { S.map.removeLayer(S.selShape); S.selShape = null; }
      setupRegionControls();
      S.mapMonth = S.nM - 1;
      selectWhole();
      setMapMonth(S.nM - 1);
      fitRegion();
      history.replaceState(null, "", `#${id}`);
    } catch (err) {
      showError(err);
      $("regionSel").value = S.region;
    } finally {
      $("regionSel").disabled = false;
    }
  }

  function initControls() {
    setupRegionControls();
    $("regionSel").addEventListener("change", (e) => switchRegion(e.target.value));
    $("baseSel").addEventListener("change", (e) => {
      S.baseline = e.target.value;
      S.table = buildTable(S.series);
      renderNow(); renderCalendar(); renderSeason(); renderFacts();
      S.overlay.redraw();
    });
    const onRange = () => {
      let a = +$("yearFrom").value, b = +$("yearTo").value;
      if (a > b) [a, b] = [b, a];
      S.yearFrom = a; S.yearTo = b;
      $("yearFrom").value = a; $("yearTo").value = b;
      renderCalendar(); renderSeason(); renderAnnual(); renderFacts();
    };
    $("yearFrom").addEventListener("change", onRange);
    $("yearTo").addEventListener("change", onRange);

    const sl = $("monthSlider");
    sl.addEventListener("input", () => setMapMonth(+sl.value));
    $("prevM").addEventListener("click", () => setMapMonth(S.mapMonth - 1));
    $("nextM").addEventListener("click", () => setMapMonth(S.mapMonth + 1));
    const playIcon = (playing) => {
      $("playBtn").innerHTML = `<svg><use href="#i-${playing ? "pause" : "play"}"/></svg>`;
      $("playBtn").setAttribute("aria-label", playing ? "Pause" : "Play through the months");
    };
    const stop = () => { clearInterval(S.playing); S.playing = null; playIcon(false); };
    $("playBtn").addEventListener("click", () => {
      if (S.playing) return stop();
      if (S.mapMonth >= S.nM - 1) setMapMonth(0);
      playIcon(true);
      S.playing = setInterval(() => {
        if (S.mapMonth >= S.nM - 1) return stop();
        setMapMonth(S.mapMonth + 1);
      }, 650);
    });

    initPops();
    $("panelClose").addEventListener("click", () => setPanel(false));
    $("panelOpen").addEventListener("click", () => setPanel(true));

    document.querySelectorAll("[data-layer]").forEach((b) => b.addEventListener("click", () => {
      document.querySelectorAll("[data-layer]").forEach((o) => o.setAttribute("aria-checked", String(o === b)));
      S.layer = b.dataset.layer;
      mapLegend();
      setMapMonth(S.mapMonth);
    }));
    document.querySelectorAll("[data-cal]").forEach((b) => b.addEventListener("click", () => {
      document.querySelectorAll("[data-cal]").forEach((o) => o.setAttribute("aria-checked", String(o === b)));
      S.calView = b.dataset.cal;
      renderCalendar();
    }));

    $("pointForm").addEventListener("submit", (e) => {
      e.preventDefault();
      const lat = parseFloat($("inLat").value), lon = parseFloat($("inLon").value), rad = parseFloat($("inRad").value) || 25;
      if (!Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) {
        $("coordsMsg").textContent = "Enter latitude and longitude in decimal degrees, for example 31.55 and 74.35.";
        return;
      }
      $("coordsMsg").textContent = "";
      if (lat < S.meta.bbox[1] - 1 || lat > S.meta.bbox[3] + 1 || lon < S.meta.bbox[0] - 1 || lon > S.meta.bbox[2] + 1) {
        $("coordsMsg").textContent = "That point is outside the area this tool covers.";
        return;
      }
      const circle = L.circle([lat, lon], { radius: rad * 1000, color: C().accent, weight: 2, dashArray: "5 4", fill: false });
      selectByLayer(circle, "circle");
      closePops();
      const right = !isPhone() && $("app").classList.contains("panel-open") ? $("panel").offsetWidth + 32 : 0;
      S.map.fitBounds(circle.getBounds(), { maxZoom: 10, paddingTopLeft: [isPhone() ? 0 : 60, 20], paddingBottomRight: [right, 100] });
    });
    $("resetSel").addEventListener("click", () => { selectWhole(); });

    $("dlMonthly").addEventListener("click", downloadMonthly);
    $("dlHotspots").addEventListener("click", downloadHotspots);
    $("dlPng").addEventListener("click", downloadPng);
    $("methodBtn").addEventListener("click", () => { renderMethod(); $("method").showModal(); });

    let rt = 0;
    window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => { renderCalendar(); renderSeason(); renderAnnual(); }, 150); });
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { setTiles(); renderAll(); });
  }

  // ------------------------------------------------------------------ downloads
  const slug = () => S.selName.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
  function save(blob, name) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  }

  function downloadMonthly() {
    const lines = ["month,hotspots_viirs_equivalent,usual_median,vs_usual_pct,rank_among_same_month,years_of_record,month_in_progress,source"];
    for (let y = S.yearFrom; y <= S.yearTo; y++) for (let mo = 0; mo < 12; mo++) {
      const r = S.table.rows[indexOf(y, mo)];
      if (!r) continue;
      lines.push([`${y}-${String(mo + 1).padStart(2, "0")}`, r.v.toFixed(1), r.usual.toFixed(1),
        r.anom === null ? "" : r.anom.toFixed(1), r.rank, r.nYears, r.partial ? `first ${r.day} days` : "", r.source].join(","));
    }
    save(new Blob([lines.join("\n") + "\n"], { type: "text/csv" }), `burning_calendar_${slug()}_${S.yearFrom}-${S.yearTo}.csv`);
    $("dlStatus").textContent = `Saved ${lines.length - 1} months.`;
  }

  async function downloadHotspots() {
    const btn = $("dlHotspots");
    btn.disabled = true;
    const parts = ["latitude,longitude,acq_date,acq_time_utc,satellite,instrument,confidence,frp_mw,daynight\n"];
    let count = 0;
    const years = d3.range(S.yearFrom, S.yearTo + 1).filter((y) => S.meta.det_years[y]);
    try {
      for (let k = 0; k < years.length; k++) {
        const y = years[k];
        $("dlStatus").textContent = `Collecting hotspots for ${y} (${k + 1} of ${years.length})`;
        const d = await loadYear(y);
        if (!d) continue;
        const out = [];
        for (let q = 0; q < d.n; q++) {
          if (!S.sel[d.cell[q]]) continue;
          const date = new Date(Date.UTC(2000, 0, 1) + d.day[q] * 86400000).toISOString().slice(0, 10);
          const conf = d.plat[q] < 2 ? d.conf[q] : (d.conf[q] >= 100 ? "h" : "n");
          out.push(`${d.lat[q].toFixed(5)},${d.lon[q].toFixed(5)},${date},${String(d.time[q]).padStart(4, "0")},${SAT_NAMES[d.plat[q]]},${SAT_SENSOR[d.plat[q]]},${conf},${d.frp[q].toFixed(2)},${d.dn[q] ? "D" : "N"}`);
        }
        count += out.length;
        if (out.length) parts.push(out.join("\n") + "\n");
      }
      save(new Blob(parts, { type: "text/csv" }), `hotspots_${slug()}_${S.yearFrom}-${S.yearTo}.csv`);
      $("dlStatus").textContent = `Saved ${fmt(count)} hotspots (all satellites, after quality filtering, before harmonization).`;
    } catch (err) {
      $("dlStatus").textContent = `Download stopped: ${err.message}. Try a shorter range of years.`;
    } finally {
      btn.disabled = false;
    }
  }

  function downloadPng() {
    const src = $("calendar").querySelector("svg");
    if (!src) return;
    const vb = src.viewBox.baseVal;
    const pad = 16, head = 46, foot = 22;
    const W = vb.width + pad * 2, H = vb.height + head + foot;
    const styles = getComputedStyle(document.documentElement);
    const bg = styles.getPropertyValue("--panel").trim() || "#ffffff";
    const ink = styles.getPropertyValue("--ink").trim(), ink2 = styles.getPropertyValue("--ink-2").trim();
    const clone = src.cloneNode(true);
    clone.querySelectorAll("text").forEach((t) => {
      if (!t.style.fill) t.setAttribute("fill", ink2);
      t.setAttribute("font-family", "Atkinson Hyperlegible, Segoe UI, sans-serif");
      if (!t.getAttribute("font-size")) t.setAttribute("font-size", "11");
    });
    const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;");
    const xml = `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">` +
      `<rect width="100%" height="100%" fill="${bg}"/>` +
      `<text x="${pad}" y="24" font-family="Barlow Condensed, Arial Narrow, sans-serif" font-weight="600" font-size="20" fill="${ink}">${esc(`Burning calendar, ${S.selName}`)}</text>` +
      `<text x="${pad}" y="40" font-family="Atkinson Hyperlegible, Segoe UI, sans-serif" font-size="11" fill="${ink2}">${esc(`${S.calView === "count" ? "Hotspots per month" : "Compared with the usual month"}, ${S.yearFrom} to ${S.yearTo}. Harmonized MODIS and VIIRS (S-NPP equivalent), NASA FIRMS.`)}</text>` +
      `<g transform="translate(${pad},${head})">${new XMLSerializer().serializeToString(clone).replace(/^<svg[^>]*>/, "").replace(/<\/svg>$/, "")}</g>` +
      `<text x="${pad}" y="${H - 8}" font-family="Atkinson Hyperlegible, Segoe UI, sans-serif" font-size="10" fill="${ink2}">* reconstructed from MODIS. Data to ${S.meta.data_end}.</text></svg>`;
    const img = new Image();
    img.onload = () => {
      const cv = document.createElement("canvas");
      cv.width = W * 2; cv.height = H * 2;
      const ctx = cv.getContext("2d");
      ctx.scale(2, 2);
      ctx.drawImage(img, 0, 0);
      cv.toBlob((b) => { save(b, `burning_calendar_${slug()}.png`); $("dlStatus").textContent = "Saved the calendar image."; }, "image/png");
    };
    img.onerror = () => { $("dlStatus").textContent = "The image could not be created in this browser."; };
    img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(xml);
  }

  // ------------------------------------------------------------------ method dialog
  function renderMethod() {
    const el = $("methodChart");
    const cl = C();
    const a = S.meta.method.annual;
    const data = a.year.map((y, k) => ({ y, raw: a.raw_all[k], aqua: a.aqua_only[k], harm: a.harmonized[k] }));
    const W = Math.max(300, Math.min(700, el.clientWidth || 640)), H = 240;
    const m = { l: 48, r: 12, t: 14, b: 24 };
    const x = d3.scaleLinear().domain(d3.extent(data, (d) => d.y)).range([m.l, W - m.r]);
    const yS = d3.scaleLinear().domain([0, d3.max(data, (d) => d.raw)]).nice().range([H - m.b, m.t]);
    const svg = d3.create("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("role", "img")
      .attr("aria-label", "Annual hotspot totals: all satellites added together jump at each launch, the harmonized series does not");
    svg.append("g").attr("class", "grid").selectAll("line").data(yS.ticks(4)).join("line")
      .attr("x1", m.l).attr("x2", W - m.r).attr("y1", yS).attr("y2", yS);
    svg.append("g").attr("class", "axis").attr("transform", `translate(${m.l},0)`)
      .call(d3.axisLeft(yS).ticks(4).tickFormat(d3.format("~s")).tickSize(0)).call((g) => g.select(".domain").remove());
    svg.append("g").attr("class", "axis").attr("transform", `translate(0,${H - m.b})`)
      .call(d3.axisBottom(x).ticks(6).tickFormat(d3.format("d")).tickSize(0)).call((g) => g.select(".domain").remove())
      .selectAll("text").attr("dy", "1.1em");
    [[2012, "S-NPP"], [2018, "NOAA-20"], [2023, "NOAA-21"]].forEach(([yr, lab]) => {
      svg.append("line").attr("x1", x(yr)).attr("x2", x(yr)).attr("y1", m.t).attr("y2", H - m.b)
        .attr("stroke", cl.median).attr("stroke-dasharray", "2 3");
      svg.append("text").attr("x", x(yr) + 4).attr("y", m.t + 8).text(lab);
    });
    const series = [
      ["raw", "All satellites added together", "#eb6834"],
      ["aqua", "Aqua MODIS alone", "#1baf7a"],
      ["harm", "Harmonized (this tool)", "#2a78d6"],
    ];
    series.forEach(([k, , col]) => {
      svg.append("path").datum(data.filter((d) => d[k] !== null)).attr("fill", "none").attr("stroke", col).attr("stroke-width", 2)
        .attr("d", d3.line().x((d) => x(d.y)).y((d) => yS(d[k])));
    });
    const legend = document.createElement("div");
    legend.className = "legend";
    legend.innerHTML = series.map(([, lab, col]) => `<span><span class="ln" style="border-color:${col}"></span>${lab}</span>`).join("");
    el.replaceChildren(svg.node(), legend);

    const mt = S.meta.method;
    const bcy = mt.backcast_years.bias_pct;
    $("methodStats").innerHTML = [
      `<li>Rebuilding earlier years from later ones: trained on 2017 onward and asked to predict 2013 to 2016, which it never saw. Monthly totals matched with a correlation of ${mt.backcast ? mt.backcast.r : "n/a"} and an overall bias of ${mt.backcast ? mt.backcast.bias_pct : "n/a"}%. Single years were within ${d3.min(bcy)}% to +${d3.max(bcy)}%.</li>`,
      `<li>Holding out one year at a time within 2013 to 2025: monthly correlation ${mt.loyo_r}, overall bias ${mt.loyo_bias_pct}%.</li>`,
      `<li>When S-NPP joined in 2012, all satellites added together jumped about ${fmt1(a.raw_all[a.year.indexOf(2012)] / a.raw_all[a.year.indexOf(2011)])} times from 2011, while the harmonized series rose ${fmt((a.harmonized[a.year.indexOf(2012)] / a.harmonized[a.year.indexOf(2011)] - 1) * 100)}%, in step with Aqua MODIS on its own.</li>`,
    ].join("");
  }

  // ------------------------------------------------------------------ start
  async function start() {
    try {
      const reg = await fetch("data/regions.json").then((r) => { if (!r.ok) throw new Error("regions.json " + r.status); return r.json(); });
      S.regions = reg.regions;
      const wanted = location.hash.slice(1);
      const first = S.regions.find((r) => r.id === wanted) || S.regions[0];
      $("regionSel").innerHTML = S.regions.map((r) => `<option value="${r.id}">${r.name}</option>`).join("");
      $("regionSel").value = first.id;
      $("regionSel").closest(".region").hidden = false;
      await load(first.id);
      initMap();
      S.mapMonth = S.nM - 1;
      initControls();
      selectWhole();
      setMapMonth(S.nM - 1);
    } catch (err) {
      showError(err);
    }
  }
  start();
})();
