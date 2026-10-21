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
    return li;
  }

  function dibujar() {
    const pendientes = items.filter((i) => !i.comprado);
    const comprados = items.filter((i) => i.comprado);
    listaPendientes.replaceChildren(...pendientes.map(crearFila));
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
    } else if (boton.dataset.accion === "borrar") {
      cambiar(`items/${id}`, { method: "DELETE" }, () => {
        items = items.filter((i) => i.id !== id);
      });
    }
  }
  listaPendientes.addEventListener("click", alTocar);
  listaComprados.addEventListener("click", alTocar);

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
})();
