(() => {
  const API = "api/";            // relativo: /lista-compras/api/ (nginx -> servicio en 8770)
  const CADA_CUANTO_MS = 5000;   // revisión de cambios hechos en otros dispositivos

  const $ = (id) => document.getElementById(id);
  const form = $("agregar");
  const campoNombre = $("nombre");
  const campoCantidad = $("cantidad");
  const listaPendientes = $("pendientes");
  const listaComprados = $("comprados");
  const plantilla = $("plantilla");
  const estado = $("estado");
  const cajaError = $("error");

  let items = [];
  let version = -1;
  // Orden en que se recorre el súper; se pide al servidor (este es el respaldo si no responde)
  let secciones = ["Frutas y verduras", "Carnes", "Lácteos y huevos", "Panadería", "Abarrotes", "Especias",
    "Bebidas", "Congelados", "Limpieza", "Higiene", "Otros"].map((nombre) => ({ nombre, icono: "" }));
  let ocupado = 0; // pedidos de cambio en curso; mientras haya, no se pisa la pantalla con la revisión

  // ---------- API ----------

  async function pedir(ruta, opciones = {}) {
    const respuesta = await fetch(API + ruta, {
      ...opciones,
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
    });
    const datos = await respuesta.json().catch(() => ({}));
    if (!respuesta.ok) throw new Error(datos.error || `Error ${respuesta.status}`);
    return datos;
  }

  function marcarEstado(tipo, texto) {
    estado.dataset.estado = tipo;
    estado.textContent = texto;
  }

  function mostrarError(texto) {
    cajaError.textContent = texto;
    cajaError.hidden = !texto;
  }

  function aplicar(datos) {
    if (datos.version === version) return;
    version = datos.version;
    items = datos.items;
    dibujar();
  }

  async function revisar() {
    if (ocupado) return;
    try {
      const datos = await pedir("items");
      if (!ocupado) aplicar(datos);
      marcarEstado("ok", "Al día");
    } catch {
      marcarEstado("error", "Sin conexión");
    }
  }

  // Cambio: se refleja de una vez en pantalla y luego se confirma con el servidor
  async function cambiar(ruta, opciones, cambioLocal) {
    ocupado++;
    if (cambioLocal) {
      cambioLocal();
      dibujar();
    }
    try {
      const datos = await pedir(ruta, opciones);
      mostrarError("");
      marcarEstado("ok", "Al día");
      version = -1; // fuerza dibujar lo que diga el servidor
      aplicar(datos);
    } catch (e) {
      mostrarError(`No se pudo guardar: ${e.message}. Revisa la conexión e intenta de nuevo.`);
      marcarEstado("error", "Sin conexión");
      version = -1;
      ocupado--;
      revisar();
      return;
    }
    ocupado--;
  }

  // ---------- Dibujo ----------

  function crearFila(item) {
    const li = plantilla.content.firstElementChild.cloneNode(true);
    li.dataset.id = item.id;
    li.classList.toggle("comprado", item.comprado);
    li.querySelector(".item-nombre").textContent = item.nombre;
    li.querySelector(".item-cantidad").textContent = item.cantidad;
    li.querySelector(".item-marcar").setAttribute(
      "aria-label",
      `${item.nombre}${item.cantidad ? ", " + item.cantidad : ""}: ${item.comprado ? "devolver a la lista" : "marcar como comprado"}`
    );
    li.querySelector(".item-borrar").setAttribute("aria-label", `Borrar ${item.nombre}`);
    li.querySelector(".item-editar").setAttribute("aria-label", `Editar ${item.nombre}`);
    return li;
  }

  // Pendientes agrupados por sección, en el orden en que se recorre el súper
  function grupos(pendientes) {
    const orden = secciones.map((s) => s.nombre);
    const porSeccion = new Map();
    for (const item of pendientes) {
      const s = orden.includes(item.seccion) ? item.seccion : "Otros";
      if (!porSeccion.has(s)) porSeccion.set(s, []);
      porSeccion.get(s).push(item);
    }
    return secciones.filter((s) => porSeccion.has(s.nombre)).map((s) => {
      const grupo = document.createElement("section");
      grupo.className = "grupo";
      const titulo = document.createElement("h3");
      titulo.className = "grupo-titulo";
      titulo.textContent = `${s.icono} ${s.nombre}`.trim();
      const ul = document.createElement("ul");
      ul.className = "items";
      ul.replaceChildren(...porSeccion.get(s.nombre).map(crearFila));
      grupo.append(titulo, ul);
      return grupo;
    });
  }

  function dibujar() {
    const pendientes = items.filter((i) => !i.comprado);
    const comprados = items.filter((i) => i.comprado);
    listaPendientes.replaceChildren(...grupos(pendientes));
    listaComprados.replaceChildren(...comprados.map(crearFila));
    $("vacio").hidden = pendientes.length > 0;
    $("carrito").hidden = comprados.length === 0;
    $("cuenta-carrito").textContent = comprados.length ? `(${comprados.length})` : "";
    document.title = pendientes.length ? `Lista de compras (${pendientes.length})` : "Lista de compras";
  }

  async function cargarSugerencias() {
    try {
      const { sugerencias } = await pedir("sugerencias");
      $("sugerencias").replaceChildren(
        ...sugerencias.map((s) => {
          const op = document.createElement("option");
          op.value = s;
          return op;
        })
      );
    } catch {
      /* sin sugerencias no pasa nada */
    }
  }

  // ---------- Eventos ----------

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const nombre = campoNombre.value.trim();
    const cantidad = campoCantidad.value.trim();
    if (!nombre) {
      campoNombre.focus();
      return;
    }
    campoNombre.value = "";
    campoCantidad.value = "";
    campoNombre.focus();
    await cambiar("items", { method: "POST", body: JSON.stringify({ nombre, cantidad }) });
    cargarSugerencias();
  });

  // 🎤 dictar varios productos de una vez: "dos leches, huevos y tortillas"
  if (window.Voz) {
    $("dictar").append(
      Voz.boton({
        modo: "lista",
        etiqueta: "Dictar productos",
        alTerminar: async ({ texto, items: dictados }) => {
          if (!dictados || !dictados.length) {
            mostrarError("No se entendió ningún producto. Intenta de nuevo.");
            return;
          }
          const antes = new Map(items.map((i) => [i.id, i.cantidad]));
          for (const { nombre, cantidad } of dictados) {
            await cambiar("items", { method: "POST", body: JSON.stringify({ nombre, cantidad }) });
          }
          cargarSugerencias();
          // Solo los productos nuevos: si un nombre ya estaba pendiente, el servidor lo juntó con el existente
          // Lo que se juntó con un producto que ya estaba sumó su cantidad: se guarda la de antes para deshacerlo
          ultimoDictado = {
            texto,
            ids: items.filter((i) => !antes.has(i.id)).map((i) => i.id),
            sumados: items.filter((i) => antes.has(i.id) && antes.get(i.id) !== i.cantidad).map((i) => ({ id: i.id, cantidad: antes.get(i.id) })),
          };
          mostrarBarraIA(`Se agregaron ${dictados.length} ${dictados.length === 1 ? "producto" : "productos"}. ¿Salió enredado?`);
        },
        alError: (m) => mostrarError(m),
      })
    );
  }

  // ✨ Ordenar con IA lo último que se dictó (servicio casa/ia, modelo local; tarda 10–30 s)
  const IA = "../ia/api/";
  let ultimoDictado = null;
  let ocultarBarra = null;

  function mostrarBarraIA(texto, conBoton = true) {
    clearTimeout(ocultarBarra);
    $("ia-barra-texto").textContent = texto;
    $("ia-ordenar").hidden = !conBoton;
    $("ia-ordenar").disabled = false;
    $("ia-barra").hidden = false;
    ocultarBarra = setTimeout(() => ($("ia-barra").hidden = true), conBoton ? 60000 : 5000);
  }

  $("ia-barra-cerrar").addEventListener("click", () => ($("ia-barra").hidden = true));

  $("ia-ordenar").addEventListener("click", async () => {
    if (!ultimoDictado) return;
    const boton = $("ia-ordenar");
    boton.disabled = true;
    clearTimeout(ocultarBarra);
    const inicio = Date.now();
    const reloj = setInterval(() => {
      $("ia-barra-texto").textContent = `Pensando… ${Math.round((Date.now() - inicio) / 1000)} s`;
    }, 1000);
    $("ia-barra-texto").textContent = "Pensando…";
    try {
      const r = await fetch(IA + "ordenar-lista", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ texto: ultimoDictado.texto }),
      });
      const datos = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(datos.error || `Error ${r.status}`);
      if (!datos.items.length) throw new Error("La IA no encontró productos en el dictado");
      // Se cambian los productos que agregó el dictado por los que ordenó la IA
      for (const id of ultimoDictado.ids) await cambiar(`items/${id}`, { method: "DELETE" });
      for (const { id, cantidad } of ultimoDictado.sumados) {
        await cambiar(`items/${id}`, { method: "PATCH", body: JSON.stringify({ cantidad }) });
      }
      for (const { nombre, cantidad } of datos.items) {
        await cambiar("items", { method: "POST", body: JSON.stringify({ nombre, cantidad }) });
      }
      ultimoDictado = null;
      mostrarBarraIA(`Ordenado con IA ✓ (${datos.items.length} ${datos.items.length === 1 ? "producto" : "productos"})`, false);
    } catch (e) {
      mostrarBarraIA(`⚠ ${e.message === "Failed to fetch" ? "No hay conexión con el servidor" : e.message}`);
    } finally {
      clearInterval(reloj);
    }
  });

  function alTocar(e) {
    const boton = e.target.closest("button[data-accion]");
    if (!boton) return;
    const id = Number(boton.closest(".item").dataset.id);
    const item = items.find((i) => i.id === id);
    if (!item) return;

    if (boton.dataset.accion === "marcar") {
      const comprado = !item.comprado;
      cambiar(`items/${id}`, { method: "PATCH", body: JSON.stringify({ comprado }) }, () => {
        item.comprado = comprado;
      });
    } else if (boton.dataset.accion === "editar") {
      abrirEditor(item);
    } else if (boton.dataset.accion === "borrar") {
      cambiar(`items/${id}`, { method: "DELETE" }, () => {
        items = items.filter((i) => i.id !== id);
      });
    }
  }
  listaPendientes.addEventListener("click", alTocar);
  listaComprados.addEventListener("click", alTocar);

  // ✎ Editar nombre, cantidad y sección (la sección elegida se recuerda para ese producto)
  const editor = $("editor");
  let editando = null;

  function abrirEditor(item) {
    editando = item.id;
    $("editor-nombre").value = item.nombre;
    $("editor-cantidad").value = item.cantidad;
    $("editor-seccion").replaceChildren(
      ...secciones.map((s) => {
        const op = document.createElement("option");
        op.value = s.nombre;
        op.textContent = `${s.icono} ${s.nombre}`.trim();
        return op;
      })
    );
    $("editor-seccion").value = item.seccion || "Otros";
    editor.showModal();
    $("editor-cantidad").focus();
  }

  $("editor-cancelar").addEventListener("click", () => editor.close());
  editor.addEventListener("click", (e) => {
    if (e.target === editor) editor.close(); // tocar fuera de la hoja la cierra
  });
  $("editor-form").addEventListener("submit", (e) => {
    const nombre = $("editor-nombre").value.trim();
    if (!nombre) {
      e.preventDefault();
      $("editor-nombre").focus();
      return;
    }
    const cantidad = $("editor-cantidad").value.trim();
    const seccion = $("editor-seccion").value;
    const id = editando;
    const item = items.find((i) => i.id === id);
    if (!item) return;
    const cambios = {};
    if (nombre !== item.nombre) cambios.nombre = nombre;
    if (cantidad !== item.cantidad) cambios.cantidad = cantidad;
    if (seccion !== item.seccion) cambios.seccion = seccion;
    if (!Object.keys(cambios).length) return;
    cambiar(`items/${id}`, { method: "PATCH", body: JSON.stringify(cambios) }, () => Object.assign(item, cambios));
  });

  async function cargarSecciones() {
    try {
      secciones = (await pedir("secciones")).secciones;
      dibujar();
    } catch {
      /* se queda con las de respaldo */
    }
  }

  $("limpiar").addEventListener("click", () => {
    if (!confirm("¿Quitar de la lista todo lo que ya está en el carrito?")) return;
    cambiar("limpiar", { method: "POST" }, () => {
      items = items.filter((i) => !i.comprado);
    });
  });

  // Revisión periódica solo con la página visible; al volver se revisa de inmediato
  let temporizador = null;
  function arrancar() {
    clearInterval(temporizador);
    revisar();
    temporizador = setInterval(revisar, CADA_CUANTO_MS);
  }
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) clearInterval(temporizador);
    else arrancar();
  });
  window.addEventListener("online", revisar);

  arrancar();
  cargarSugerencias();
  cargarSecciones();
})();
