// Página del cubo: mapa con los bloques calculados, visor por mes y capa, y chat con los datos.
// Habla con la API de `cdcol web` (src/cdcol_fm/chat/servidor.py): en local, en el mismo origen y
// sin sesión; desplegada, en la URL de config.js y con el token de Cognito (ADR 0006).
"use strict";

const CONFIG = window.CDCOL || {};
const estado = { zonas: [], zona: null, seleccion: new Set(), conversacion: null, capas: [] };
const $ = (id) => document.getElementById(id);

// --- Sesión (Cognito, flujo de código con PKCE) --------------------------------------------

const sesion = {
  get token() { return sessionStorage.getItem("cdcol-token"); },
  get vence() { return Number(sessionStorage.getItem("cdcol-vence") || 0); },
  guardar(t) {
    sessionStorage.setItem("cdcol-token", t.access_token);
    sessionStorage.setItem("cdcol-vence", String(Date.now() + (t.expires_in - 60) * 1000));
    if (t.refresh_token) sessionStorage.setItem("cdcol-refresco", t.refresh_token);
  },
  borrar() { ["cdcol-token", "cdcol-vence", "cdcol-refresco"].forEach((k) => sessionStorage.removeItem(k)); },
};
const volverA = () => location.origin + location.pathname;

function base64url(bytes) {
  return btoa(String.fromCharCode(...new Uint8Array(bytes))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function pedirToken(parametros) {
  const r = await fetch(`${CONFIG.cognito.dominio}/oauth2/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ client_id: CONFIG.cognito.cliente, ...parametros }),
  });
  if (!r.ok) throw new Error("no se pudo iniciar sesión");
  sesion.guardar(await r.json());
}

async function entrar() {
  const verificador = base64url(crypto.getRandomValues(new Uint8Array(32)));
  const reto = base64url(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verificador)));
  sessionStorage.setItem("cdcol-verificador", verificador);
  const q = new URLSearchParams({
    response_type: "code", client_id: CONFIG.cognito.cliente, redirect_uri: volverA(),
    scope: "openid email aws.cognito.signin.user.admin",
    code_challenge_method: "S256", code_challenge: reto,
  });
  location.assign(`${CONFIG.cognito.dominio}/oauth2/authorize?${q}`);
}

// Devuelve un token vigente o redirige al inicio de sesión (y entonces no vuelve).
async function asegurarSesion() {
  if (!CONFIG.cognito) return true;
  const codigo = new URLSearchParams(location.search).get("code");
  if (codigo) {
    history.replaceState(null, "", volverA());
    await pedirToken({
      grant_type: "authorization_code", code: codigo, redirect_uri: volverA(),
      code_verifier: sessionStorage.getItem("cdcol-verificador") || "",
    });
  }
  if (sesion.token && Date.now() < sesion.vence) return true;
  const refresco = sessionStorage.getItem("cdcol-refresco");
  if (refresco) {
    try {
      await pedirToken({ grant_type: "refresh_token", refresh_token: refresco });
      return true;
    } catch { /* se vuelve a entrar */ }
  }
  sesion.borrar();
  await entrar();
  return false;
}

async function api(ruta, opciones = {}) {
  if (!(await asegurarSesion())) return new Promise(() => {}); // se fue a iniciar sesión
  const cabeceras = { ...(opciones.headers || {}) };
  if (CONFIG.cognito) cabeceras.Authorization = `Bearer ${sesion.token}`;
  const r = await fetch(`${CONFIG.api || ""}${ruta}`, { ...opciones, headers: cabeceras });
  if (r.status === 401 && CONFIG.cognito) {
    sesion.borrar();
    await entrar();
    return new Promise(() => {});
  }
  return r;
}

function salir() {
  sesion.borrar();
  const q = new URLSearchParams({ client_id: CONFIG.cognito.cliente, logout_uri: volverA() });
  location.assign(`${CONFIG.cognito.dominio}/logout?${q}`);
}

const mapa = new maplibregl.Map({
  container: "mapa",
  center: [-73.8, 3.0],
  zoom: 6,
  style: {
    version: 8,
    sources: {
      osm: {
        type: "raster", tileSize: 256, maxzoom: 19,
        tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
        attribution: "© colaboradores de OpenStreetMap",
      },
    },
    layers: [{ id: "osm", type: "raster", source: "osm" }],
  },
});
mapa.addControl(new maplibregl.NavigationControl(), "top-right");

// --- Bloques -------------------------------------------------------------------------------

function geojsonBloques(zona) {
  return {
    type: "FeatureCollection",
    features: zona.bloques.map((b) => ({
      type: "Feature",
      id: b.id,
      properties: { id: b.id, meses: b.meses.length },
      geometry: { type: "Polygon", coordinates: [[...b.esquinas, b.esquinas[0]]] },
    })),
  };
}

function pintarBloques() {
  const zona = estado.zona;
  const datos = geojsonBloques(zona);
  if (mapa.getSource("bloques")) {
    mapa.getSource("bloques").setData(datos);
  } else {
    mapa.addSource("bloques", { type: "geojson", data: datos, promoteId: "id" });
    mapa.addLayer({
      id: "bloques-relleno", type: "fill", source: "bloques",
      paint: {
        "fill-color": "#1f6f5c",
        "fill-opacity": ["case", ["boolean", ["feature-state", "elegido"], false], 0.25, 0.02],
      },
    });
    mapa.addLayer({
      id: "bloques-borde", type: "line", source: "bloques",
      paint: { "line-color": "#1f6f5c", "line-width": 1.5 },
    });
    mapa.on("click", "bloques-relleno", (e) => alternarBloque(e.features[0].properties.id));
    mapa.on("mouseenter", "bloques-relleno", () => (mapa.getCanvas().style.cursor = "pointer"));
    mapa.on("mouseleave", "bloques-relleno", () => (mapa.getCanvas().style.cursor = ""));
  }
  const limites = new maplibregl.LngLatBounds();
  zona.bloques.forEach((b) => b.esquinas.forEach((c) => limites.extend(c)));
  mapa.fitBounds(limites, { padding: 60, maxZoom: 12 });
}

function alternarBloque(id) {
  const elegido = !estado.seleccion.has(id);
  elegido ? estado.seleccion.add(id) : estado.seleccion.delete(id);
  mapa.setFeatureState({ source: "bloques", id }, { elegido });
  const n = estado.seleccion.size;
  $("seleccion").textContent = n
    ? `${n} bloque${n > 1 ? "s" : ""} elegido${n > 1 ? "s" : ""}: las preguntas se limitan a ${n > 1 ? "ellos" : "él"}.`
    : "Sin selección: las preguntas usan toda la zona.";
  if ($("capa").value) verCapa();
}

// --- Zona, mes y capa ----------------------------------------------------------------------

function elegirZona(id) {
  estado.zona = estado.zonas.find((z) => z.zona === id);
  for (const b of estado.seleccion) mapa.setFeatureState({ source: "bloques", id: b }, { elegido: false });
  estado.seleccion.clear();
  const meses = [...new Set(estado.zona.bloques.flatMap((b) => b.meses))].sort();
  $("mes").replaceChildren(...meses.map((m) => new Option(m, m)));
  $("seleccion").textContent = "Haz clic en los bloques para elegir dónde preguntar.";
  pintarBloques();
  quitarCapas();
}

function quitarCapas() {
  for (const id of estado.capas) {
    if (mapa.getLayer(id)) mapa.removeLayer(id);
    if (mapa.getSource(id)) mapa.removeSource(id);
  }
  estado.capas = [];
  $("leyenda").hidden = true;
}

function mostrarFiguraMapa(figura) {
  quitarCapas();
  figura.piezas.forEach((p, i) => {
    const id = `capa-${i}`;
    mapa.addSource(id, { type: "image", url: p.url || `/api/imagen/${p.imagen}`, coordinates: p.esquinas });
    mapa.addLayer({ id, type: "raster", source: id, paint: { "raster-opacity": 0.9 } }, "bloques-relleno");
    estado.capas.push(id);
  });
  $("leyenda").textContent = `${figura.mes} · ${figura.leyenda}`;
  $("leyenda").hidden = false;
  $("mes").value = figura.mes;
  $("capa").value = [...$("capa").options].some((o) => o.value === figura.capa) ? figura.capa : "";
}

async function verCapa() {
  const capa = $("capa").value;
  if (!capa) return quitarCapas();
  const q = new URLSearchParams({ zona: estado.zona.zona, capa, mes: $("mes").value });
  if (estado.seleccion.size) q.set("bloques", [...estado.seleccion].join(","));
  const r = await api(`/api/mapa?${q}`);
  const datos = await r.json();
  if (!r.ok) return agregarError(datos.error);
  mostrarFiguraMapa(datos);
}

// --- Chat ----------------------------------------------------------------------------------

function escapar(texto) {
  const d = document.createElement("div");
  d.textContent = texto;
  return d.innerHTML;
}

// Markdown mínimo: párrafos, viñetas y negritas. Se escapa antes de dar formato.
function formatear(texto) {
  const negrita = (s) => escapar(s).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  return texto.split(/\n{2,}/).map((bloque) => {
    const lineas = bloque.split("\n");
    if (lineas.every((l) => /^\s*[-•*]\s+/.test(l))) {
      return `<ul>${lineas.map((l) => `<li>${negrita(l.replace(/^\s*[-•*]\s+/, ""))}</li>`).join("")}</ul>`;
    }
    return `<p>${lineas.map(negrita).join("<br>")}</p>`;
  }).join("");
}

function grafico(figura) {
  const puntos = figura.puntos.filter((p) => p.p50 !== null && p.p50 !== undefined);
  if (puntos.length < 2) return null;
  const W = 400, H = 150, m = { i: 40, d: 10, s: 10, b: 28 };
  const valores = puntos.flatMap((p) => [p.p10, p.p50, p.p90]).filter((v) => v !== null && v !== undefined);
  let min = Math.min(...valores), max = Math.max(...valores);
  if (min === max) { min -= 1; max += 1; }
  const x = (i) => m.i + (i * (W - m.i - m.d)) / (puntos.length - 1);
  const y = (v) => H - m.b - ((v - min) * (H - m.s - m.b)) / (max - min);
  const conBanda = puntos.every((p) => p.p10 !== undefined && p.p10 !== null);
  const banda = conBanda
    ? `<path d="M${puntos.map((p, i) => `${x(i)},${y(p.p90)}`).join("L")}L${puntos.map((p, i) => `${x(i)},${y(p.p10)}`).reverse().join("L")}Z" fill="var(--acento)" opacity="0.15"/>`
    : "";
  const linea = `<path d="M${puntos.map((p, i) => `${x(i)},${y(p.p50)}`).join("L")}" fill="none" stroke="var(--acento)" stroke-width="2"/>`;
  const marcas = puntos.map((p, i) => `<circle cx="${x(i)}" cy="${y(p.p50)}" r="3" fill="var(--acento)"><title>${p.mes}: ${p.p50}</title></circle>`).join("");
  const paso = Math.ceil(puntos.length / 6);
  const ejeX = puntos.map((p, i) => (i % paso ? "" : `<text x="${x(i)}" y="${H - 8}" font-size="10" text-anchor="middle" fill="currentColor">${p.mes}</text>`)).join("");
  const ejeY = [min, max].map((v) => `<text x="${m.i - 4}" y="${y(v) + 3}" font-size="10" text-anchor="end" fill="currentColor">${Number(v.toPrecision(3))}</text>`).join("");
  const div = document.createElement("div");
  div.className = "grafico";
  div.innerHTML = `<div class="titulo">${escapar(figura.variable)}${figura.unidad ? ` (${escapar(figura.unidad)})` : ""} por mes${conBanda ? " · línea: mediana; banda: p10–p90" : ""}</div>
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Serie de ${escapar(figura.variable)}">${banda}${linea}${marcas}${ejeX}${ejeY}</svg>`;
  return div;
}

function agregar(clase, html) {
  const div = document.createElement("div");
  div.className = `msg ${clase}`;
  if (html !== undefined) div.innerHTML = html;
  $("mensajes").append(div);
  $("mensajes").scrollTop = $("mensajes").scrollHeight;
  return div;
}

function agregarError(texto) {
  agregar("error", escapar(`No se pudo: ${texto}`));
}

function agregarRespuesta(r) {
  const div = agregar("asistente", formatear(r.texto || "(sin texto)"));
  for (const f of r.figuras) {
    if (f.tipo === "serie") {
      const g = grafico(f);
      if (g) div.append(g);
    } else if (f.tipo === "mapa") {
      mostrarFiguraMapa(f);
      const nota = document.createElement("p");
      nota.className = "nota";
      nota.textContent = `En el mapa: ${f.capa}, ${f.mes}.`;
      div.append(nota);
    }
  }
  if (r.pasos.length) {
    const det = document.createElement("details");
    det.innerHTML = `<summary>Datos usados (${r.pasos.length} consulta${r.pasos.length > 1 ? "s" : ""})</summary>`;
    const pre = document.createElement("pre");
    pre.textContent = r.pasos.map((p) => `${p.error ? "✗ " : ""}${p.herramienta} ${JSON.stringify(p.entrada)}\n${JSON.stringify(p.salida, null, 1)}`).join("\n\n");
    det.append(pre);
    div.append(det);
  }
}

async function preguntar(texto) {
  document.querySelector(".bienvenida")?.remove();
  agregar("usuario", escapar(texto));
  const espera = agregar("esperando", "Consultando los datos…");
  $("enviar").disabled = true;
  try {
    const r = await api("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        conversacion: estado.conversacion,
        zona: estado.zona?.zona,
        bloques: [...estado.seleccion],
        pregunta: texto,
      }),
    });
    const datos = await r.json();
    espera.remove();
    if (!r.ok) return agregarError(datos.error);
    estado.conversacion = datos.conversacion;
    agregarRespuesta(datos);
  } catch (e) {
    espera.remove();
    agregarError(e.message);
  } finally {
    $("enviar").disabled = false;
    $("pregunta").focus();
  }
}

// --- Arranque ------------------------------------------------------------------------------

$("formulario").addEventListener("submit", (e) => {
  e.preventDefault();
  const texto = $("pregunta").value.trim();
  if (!texto || $("enviar").disabled) return;
  $("pregunta").value = "";
  preguntar(texto);
});
$("pregunta").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    $("formulario").requestSubmit();
  }
});
$("sugerencias").addEventListener("click", (e) => {
  if (e.target.tagName === "BUTTON") preguntar(e.target.textContent);
});
$("zona").addEventListener("change", (e) => elegirZona(e.target.value));
$("mes").addEventListener("change", () => $("capa").value && verCapa());
$("capa").addEventListener("change", verCapa);

mapa.on("load", async () => {
  if (CONFIG.cognito) {
    $("sesion").hidden = false;
    $("salir").addEventListener("click", salir);
  }
  const r = await api("/api/zonas");
  if (!r.ok) return agregarError((await r.json()).error);
  estado.zonas = await r.json();
  if (!estado.zonas.length) return agregarError("no hay zonas con datos");
  $("zona").replaceChildren(...estado.zonas.map((z) => new Option(z.zona, z.zona)));
  elegirZona(estado.zonas[0].zona);
});
