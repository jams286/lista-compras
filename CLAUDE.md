# lista-compras (casa)

Lista de compras compartida entre los celulares de la casa y la tablet (vía el hub `infra/home`).

## Qué hace

- Agregar producto con cantidad opcional (texto libre: "2", "1 paquete"). Si ya está pendiente con el mismo nombre, solo se actualiza la cantidad.
- Tocar un producto lo marca como comprado (baja a "En el carrito"); tocarlo otra vez lo devuelve. ✕ lo borra. "Limpiar comprados" vacía el carrito.
- Sugerencias al escribir (`<datalist>`) con lo que se ha agregado antes, los más frecuentes primero.
- 🎤 Dictado (`../voz/voz.js`, modo lista): "dos leches, huevos y tortillas" agrega tres productos, cada uno con su cantidad. Si `voz.js` no carga, el botón no aparece y la fila vuelve a 3 columnas (`.agregar:has(.dictar:empty)`).
- ✨ Después de dictar aparece una barra "¿Salió enredado? ✨ Ordenar con IA": manda el texto dictado a `../ia/api/ordenar-lista` (proyecto `casa/ia`, modelo local, 10–30 s) y cambia los productos que agregó ese dictado (solo los nuevos; los que se juntaron con uno ya pendiente se quedan) por los que devuelve la IA.
- Otras tools agregan productos con `POST /api/items`: la cocina (ingredientes de una receta y lo que se acaba en la despensa).

## Cómo está hecho

- `servidor.py`: `ThreadingHTTPServer` + `sqlite3`, solo biblioteca estándar, en `127.0.0.1:8770`. Tablas `items`, `historial` (para sugerencias) y `meta` (contador `version`, sube con cada cambio). Cada respuesta de cambio devuelve la lista completa. Variables `LISTA_BD` y `LISTA_PUERTO` para probar sin tocar los datos reales.
- BD: `~/.local/share/casa/lista-compras.db` (WAL). No va en git.
- `web/`: página estática (sin frameworks). Revisa `api/items` cada 5 s con la pestaña visible y al volver a ella; solo redibuja si cambió `version`. Los cambios se reflejan al tiro en pantalla y luego se confirman con el servidor; si falla, muestra un error y recarga del servidor.
- Rutas relativas (`api/...`) para que funcione bajo `/lista-compras/`.
- Sin login: es solo red local.

## Dónde corre

- Página: http://192.168.1.4/lista-compras/ (archivos en `/var/www/lista-compras/`, copiados de `web/`).
- API: nginx publica `/lista-compras/api/` → `127.0.0.1:8770/api/` (config en `infra/nginx`).
- Servicio systemd de usuario `lista-compras.service` (copia en `servicio/`; linger activo, arranca sin sesión iniciada).
- Comandos de publicación, servicio y respaldo en el README.
