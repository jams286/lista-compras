# lista-compras (casa)

Tracker: lista-compras

Lista de compras compartida entre los celulares de la casa y la tablet (vía el hub `infra/home`).

## Qué hace

- Agregar producto con cantidad opcional (texto libre: "2", "1 paquete"). Si ya está pendiente, **se suma la cantidad** en vez de crear otra entrada (v2):
  - Mismo producto = misma `clave()`: sin tildes, mayúsculas, paréntesis ni plural ("Limón" = "limones", "Papas (unas 4 grandes)" = "papa"). La raíz es aproximada (quita "s", luego "e" tras consonante, z→c), igual en los dos lados.
  - `sumar_cantidades()`: misma unidad (g/gr/gramos, kg/kilo, l/litro…) o sin unidad → suma con fracciones ("1/2" + "8" = "8 1/2"); un número sin unidad cuenta como piezas de la otra ("1 lata" + "1" = "2 latas") salvo pesos y volúmenes. Si no se puede, se juntan como texto ("1 kg + 2 bolsas"). Máx. 40 caracteres.
  - Los comprados no se suman: el producto vuelve como pendiente aparte.
- Tocar un producto lo marca como comprado (baja a "En el carrito"); tocarlo otra vez lo devuelve. ✎ abre una hoja (`<dialog>`) para cambiar nombre, cantidad y sección (v2). ✕ lo borra. "Limpiar comprados" vacía el carrito.
- Pendientes agrupados por sección, en el orden en que se recorre el súper (`SECCIONES` en `servidor.py`, `GET /api/secciones`). `adivinar_seccion()` usa un diccionario de palabras clave: gana la frase más larga ("ajo en polvo" → Especias le gana a "ajo" → Verduras); si nada coincide, "Otros". Lo que alguien elige a mano en ✎ se guarda en la tabla `secciones` (por `clave()`) y se usa la próxima vez que se agregue ese producto. Al arrancar, los items sin sección reciben la del diccionario.
- Sugerencias al escribir (`<datalist>`) con lo que se ha agregado antes, los más frecuentes primero.
- 🎤 Dictado (`../voz/voz.js`, modo lista): "dos leches, huevos y tortillas" agrega tres productos, cada uno con su cantidad. Si `voz.js` no carga, el botón no aparece y la fila vuelve a 3 columnas (`.agregar:has(.dictar:empty)`).
- ✨ Después de dictar aparece una barra "¿Salió enredado? ✨ Ordenar con IA": manda el texto dictado a `../ia/api/ordenar-lista` (proyecto `casa/ia`, modelo local, 10–30 s) y cambia los productos que agregó ese dictado por los que devuelve la IA. Los que se sumaron a uno ya pendiente vuelven primero a su cantidad de antes (si no, se sumarían dos veces).
- Otras tools agregan productos con `POST /api/items`: la cocina (ingredientes de una receta y lo que se acaba en la despensa).

## Cómo está hecho

- `servidor.py`: `ThreadingHTTPServer` + `sqlite3`, solo biblioteca estándar, en `127.0.0.1:8770`. Tablas `items` (con `seccion`), `historial` (para sugerencias), `secciones` (las elegidas a mano) y `meta` (contador `version`, sube con cada cambio). Las columnas nuevas se agregan solas al arrancar. Cada respuesta de cambio devuelve la lista completa. Variables `LISTA_BD` y `LISTA_PUERTO` para probar sin tocar los datos reales.
- BD: `~/.local/share/casa/lista-compras.db` (WAL). No va en git.
- `web/`: página estática (sin frameworks). Revisa `api/items` cada 5 s con la pestaña visible y al volver a ella; solo redibuja si cambió `version`. Los cambios se reflejan al tiro en pantalla y luego se confirman con el servidor; si falla, muestra un error y recarga del servidor.
- Rutas relativas (`api/...`) para que funcione bajo `/lista-compras/`.
- Sin login: es solo red local.

## Dónde corre

- Página: https://192.168.1.4/lista-compras/ (archivos en `/var/www/lista-compras/`, copiados de `web/`).
- API: nginx publica `/lista-compras/api/` → `127.0.0.1:8770/api/` (config en `infra/nginx`).
- Servicio systemd de usuario `lista-compras.service` (copia en `servicio/`; linger activo, arranca sin sesión iniciada).
- Comandos de publicación, servicio y respaldo en el README.

## Pruebas

- `python3 -m unittest -v` (`test_servidor.py`, BD temporal): clave, suma de cantidades, secciones, edición y migración.
- UI: Playwright (venv de `personal/rm-ecommerce`) contra servidores de prueba con `LISTA_BD`/`LISTA_PUERTO` y un proxy que imite a nginx. El puerto 18770 lo ocupa un servidor de prueba viejo (31 oct); usar otro.
