"""Servicio de la lista de compras: API JSON sobre SQLite.

Escucha solo en 127.0.0.1; nginx publica /lista-compras/api/ -> /api/.
Sin dependencias externas (solo la biblioteca estándar).

    python3 servidor.py

Rutas:
    GET    /api/items             lista completa + versión
    POST   /api/items             {"nombre", "cantidad"}  agrega (si ya está pendiente, suma la cantidad)
    PATCH  /api/items/<id>        {"comprado"?, "nombre"?, "cantidad"?, "seccion"?}
    GET    /api/secciones         secciones del súper, en el orden en que se recorren
    DELETE /api/items/<id>
    POST   /api/limpiar           borra los comprados
    GET    /api/sugerencias       nombres usados antes, los más frecuentes primero
"""

import json
import os
import re
import sqlite3
import threading
import unicodedata
from datetime import datetime
from fractions import Fraction
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = '127.0.0.1'
# Se pueden cambiar para pruebas sin tocar los datos reales
PUERTO = int(os.environ.get('LISTA_PUERTO', 8770))
BD = Path(os.environ.get('LISTA_BD', Path.home() / '.local/share/casa/lista-compras.db'))
MAX_CUERPO = 4096
MAX_NOMBRE, MAX_CANTIDAD = 60, 40

candado = threading.Lock()   # una escritura a la vez


# ---------- Base de datos ----------

def conectar():
    con = sqlite3.connect(BD, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def preparar_bd():
    BD.parent.mkdir(parents=True, exist_ok=True)
    with conectar() as con:
        con.executescript('''
            PRAGMA journal_mode = WAL;
            CREATE TABLE IF NOT EXISTS items (
                id          INTEGER PRIMARY KEY,
                nombre      TEXT NOT NULL,
                cantidad    TEXT NOT NULL DEFAULT '',
                comprado    INTEGER NOT NULL DEFAULT 0,
                creado      TEXT NOT NULL,
                comprado_en TEXT
            );
            CREATE TABLE IF NOT EXISTS historial (
                clave       TEXT PRIMARY KEY,   -- nombre en minúsculas
                nombre      TEXT NOT NULL,      -- cómo se escribió la última vez
                veces       INTEGER NOT NULL DEFAULT 0,
                ultima_vez  TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS meta (
                clave TEXT PRIMARY KEY,
                valor INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS secciones (
                clave   TEXT PRIMARY KEY,   -- clave() del nombre
                seccion TEXT NOT NULL       -- la que alguien eligió a mano; se recuerda
            );
            INSERT OR IGNORE INTO meta (clave, valor) VALUES ('version', 0);
        ''')
        columnas = {f[1] for f in con.execute('PRAGMA table_info(items)')}
        if 'seccion' not in columnas:
            con.execute("ALTER TABLE items ADD COLUMN seccion TEXT NOT NULL DEFAULT ''")
        for f in con.execute("SELECT id, nombre FROM items WHERE seccion = ''").fetchall():
            con.execute('UPDATE items SET seccion = ? WHERE id = ?', (seccion_de(con, f[1]), f[0]))


def ahora():
    return datetime.now().isoformat(timespec='seconds')


def subir_version(con):
    con.execute("UPDATE meta SET valor = valor + 1 WHERE clave = 'version'")


def leer_todo(con):
    version = con.execute("SELECT valor FROM meta WHERE clave = 'version'").fetchone()[0]
    filas = con.execute('''
        SELECT id, nombre, cantidad, seccion, comprado, creado, comprado_en FROM items
        ORDER BY comprado, CASE WHEN comprado THEN comprado_en END DESC, id
    ''').fetchall()
    items = [dict(f, comprado=bool(f['comprado'])) for f in filas]
    return {'version': version, 'items': items}


def limpiar_texto(valor, maximo):
    if not isinstance(valor, str):
        return ''
    return re.sub(r'\s+', ' ', valor).strip()[:maximo]


# ---------- Nombres, cantidades y secciones ----------

def _sin_tildes(texto):
    return ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')


def _raiz(palabra):
    """Singular aproximado, igual para 'limón' y 'limones', 'chile' y 'chiles', 'nuez' y 'nueces'."""
    if len(palabra) > 3 and palabra.endswith('s'):
        palabra = palabra[:-1]
    if len(palabra) > 3 and palabra.endswith('e') and palabra[-2] not in 'aeiou':
        palabra = palabra[:-1]
    if palabra.endswith('z'):
        palabra = palabra[:-1] + 'c'
    return palabra


def palabras(nombre):
    t = _sin_tildes(nombre.lower())
    t = re.sub(r'\([^)]*\)', ' ', t)           # "Papas (unas 4 grandes)" -> "papas"
    return [_raiz(w) for w in re.findall(r'[a-zñ0-9]+', t)]


def clave(nombre):
    """Para reconocer el mismo producto escrito distinto: sin tildes, mayúsculas, plural ni paréntesis."""
    return ' '.join(palabras(nombre)) or nombre.strip().lower()


NUMEROS = {'un': 1, 'uno': 1, 'una': 1, 'dos': 2, 'tres': 3, 'cuatro': 4, 'cinco': 5, 'seis': 6, 'siete': 7,
           'ocho': 8, 'nueve': 9, 'diez': 10, 'once': 11, 'doce': 12, 'medio': Fraction(1, 2), 'media': Fraction(1, 2)}
UNIDADES = {'g': 'g', 'gr': 'g', 'grs': 'g', 'gramo': 'g', 'kg': 'kg', 'kilo': 'kg', 'kilogramo': 'kg',
            'l': 'l', 'lt': 'l', 'lts': 'l', 'litro': 'l', 'ml': 'ml', 'mililitro': 'ml', 'lb': 'lb', 'libra': 'lb'}
RE_CANTIDAD = re.compile(r'^(?:(\d+)\s+(\d+)/(\d+)|(\d+)/(\d+)|(\d+(?:[.,]\d+)?)|([a-záéíóú]+))(?:\s+(?:de\s+)?(.+))?$', re.IGNORECASE)


def leer_cantidad(texto):
    """'1 1/2 kg' -> (Fraction(3, 2), 'kg'); 'dos' -> (2, ''); si no empieza con número -> None."""
    m = RE_CANTIDAD.match(texto.strip())
    if not m:
        return None
    if m[1]:
        n = int(m[1]) + Fraction(int(m[2]), int(m[3]))
    elif m[4]:
        if int(m[5]) == 0:
            return None
        n = Fraction(int(m[4]), int(m[5]))
    elif m[6]:
        n = Fraction(m[6].replace(',', '.'))
    elif m[7].lower() in NUMEROS:
        n = Fraction(NUMEROS[m[7].lower()])
    else:
        return None
    return n, (m[8] or '').strip()


def _unidad_clave(unidad):
    u = clave(unidad)
    return UNIDADES.get(u, u)


def escribir_numero(n):
    if n.denominator == 1:
        return str(n.numerator)
    if n.denominator in (2, 3, 4):
        entero, resto = divmod(n.numerator, n.denominator)
        return f'{entero} {resto}/{n.denominator}' if entero else f'{resto}/{n.denominator}'
    return f'{float(n):.2f}'.rstrip('0').rstrip('.')


def _plural(unidad, n):
    if n <= 1 or len(unidad) <= 2 or ' ' in unidad or unidad.endswith('s'):
        return unidad
    return unidad + ('s' if unidad[-1] in 'aeiouáéíóú' else 'es')


def sumar_cantidades(a, b):
    """'1/2' + '8' -> '8 1/2'; '1 litro' + '1 litro' -> '2 litros'; '1 kg' + '2 bolsas' -> '1 kg + 2 bolsas'."""
    if not a or not b:
        return a or b
    x, y = leer_cantidad(a), leer_cantidad(b)
    # Sin unidad cuenta como "piezas" de la otra ('1 lata' + '1' = '2 latas'), pero no de un peso o volumen
    contable = lambda u: _unidad_clave(u) not in UNIDADES.values()
    if x and y and (_unidad_clave(x[1]) == _unidad_clave(y[1])
                    or (not x[1] and contable(y[1])) or (not y[1] and contable(x[1]))):
        n = x[0] + y[0]
        unidad = x[1] or y[1]
        return f'{escribir_numero(n)} {_plural(unidad, n)}'.strip()
    return f'{a} + {b}'


SECCIONES = [
    ('Frutas y verduras', '🥬'), ('Carnes', '🥩'), ('Lácteos y huevos', '🧀'), ('Panadería', '🍞'),
    ('Abarrotes', '🥫'), ('Especias', '🧂'), ('Bebidas', '🥤'), ('Congelados', '🧊'),
    ('Limpieza', '🧽'), ('Higiene', '🧴'), ('Otros', '📦'),
]
NOMBRES_SECCION = [n for n, _ in SECCIONES]
_PALABRAS_SECCION = {
    'Frutas y verduras': 'tomate cebolla lechuga papa limon limones aguacate chile ajo zanahoria pepino brocoli '
                         'repollo cilantro perejil hierbabuena apio chayote ejote elote guisquil pipian loroco '
                         'banano platano manzana pera naranja mandarina uva fresa piña sandia melon papaya mango '
                         'jengibre espinaca hongo champiñon jalapeño fruta verdura berenjena calabacin pimiento rabano',
    'Carnes': 'carne res pollo cerdo tocino jamon salchicha chorizo pescado camaron atun_fresco pechuga muslo '
              'costilla bistec molida lomo pavo mortadela salami',
    'Lácteos y huevos': 'leche queso crema mantequilla yogur yogurt huevo requeson quesillo margarina',
    'Panadería': 'pan tortilla pan_de_hamburguesa bollo baguette galleta pastel',
    'Abarrotes': 'arroz frijol pasta espagueti fideo aceite azucar harina sal_de_mesa mayonesa ketchup catsup '
                 'mostaza pepinillo chipotle_en_adobo salsa atun sardina enlatado lata cafe te cereal avena '
                 'consome caldo vinagre miel mermelada cacahuate mani maiz maicena gelatina chocolate soya '
                 'polvo_para_hornear levadura',
    'Especias': 'sal pimienta paprika comino oregano canela laurel tomillo ajo_en_polvo cebolla_en_polvo '
                'especia condimento curry nuez_moscada clavo achiote',
    'Bebidas': 'agua agua_mineral refresco soda gaseosa jugo cerveza vino licor bebida',
    'Congelados': 'hielo helado congelado',
    'Limpieza': 'cloro detergente suavizante bolsa_de_basura esponja paño guante limpia_vidrio limpiavidrio '
                'desinfectante jabon_para_traste lavaplatos escoba trapeador servilleta papel_aluminio '
                'papel_toalla insecticida aromatizante',
    'Higiene': 'pasta_de_diente cepillo_de_diente champu shampoo jabon desodorante papel_higienico toalla_femenina '
               'rastrillo crema_corporal hilo_dental enjuague pañal algodon',
}
_REGLAS_SECCION = sorted(
    ((palabras(frase.replace('_', ' ')), seccion) for seccion, frases in _PALABRAS_SECCION.items() for frase in frases.split()),
    key=lambda r: -len(r[0]),
)


def adivinar_seccion(nombre):
    """La frase más larga que aparezca gana: 'ajo en polvo' (Especias) le gana a 'ajo' (Verduras)."""
    ws = palabras(nombre)
    for frase, seccion in _REGLAS_SECCION:
        n = len(frase)
        if any(ws[i:i + n] == frase for i in range(len(ws) - n + 1)):
            return seccion
    return 'Otros'


def seccion_de(con, nombre):
    """La que se eligió a mano para ese producto, si alguien lo hizo; si no, la del diccionario."""
    fila = con.execute('SELECT seccion FROM secciones WHERE clave = ?', (clave(nombre),)).fetchone()
    return fila[0] if fila else adivinar_seccion(nombre)


# ---------- Operaciones ----------

def agregar(datos):
    nombre = limpiar_texto(datos.get('nombre'), MAX_NOMBRE)
    cantidad = limpiar_texto(datos.get('cantidad'), MAX_CANTIDAD)
    if not nombre:
        raise ValueError('Falta el nombre')
    with candado, conectar() as con:
        # Si ya está pendiente (aunque esté escrito distinto: "Limón" / "limones"), se suma la cantidad
        k = clave(nombre)
        existente = next((f for f in con.execute('SELECT id, nombre, cantidad FROM items WHERE comprado = 0')
                          if clave(f['nombre']) == k), None)
        if existente:
            total = sumar_cantidades(existente['cantidad'], cantidad)[:MAX_CANTIDAD]
            con.execute('UPDATE items SET cantidad = ? WHERE id = ?', (total, existente['id']))
        else:
            con.execute('INSERT INTO items (nombre, cantidad, seccion, creado) VALUES (?, ?, ?, ?)',
                        (nombre, cantidad, seccion_de(con, nombre), ahora()))
        con.execute('''
            INSERT INTO historial (clave, nombre, veces, ultima_vez) VALUES (lower(?), ?, 1, ?)
            ON CONFLICT(clave) DO UPDATE SET nombre = excluded.nombre,
                veces = veces + 1, ultima_vez = excluded.ultima_vez
        ''', (nombre, nombre, ahora()))
        subir_version(con)
        return leer_todo(con)


def modificar(item_id, datos):
    cambios, valores = [], []
    if 'comprado' in datos:
        comprado = bool(datos['comprado'])
        cambios += ['comprado = ?', 'comprado_en = ?']
        valores += [int(comprado), ahora() if comprado else None]
    if 'nombre' in datos:
        nombre = limpiar_texto(datos['nombre'], MAX_NOMBRE)
        if not nombre:
            raise ValueError('El nombre no puede quedar vacío')
        cambios.append('nombre = ?')
        valores.append(nombre)
    if 'cantidad' in datos:
        cambios.append('cantidad = ?')
        valores.append(limpiar_texto(datos['cantidad'], MAX_CANTIDAD))
    seccion = datos.get('seccion')
    if seccion is not None:
        if seccion not in NOMBRES_SECCION:
            raise ValueError('Sección desconocida')
        cambios.append('seccion = ?')
        valores.append(seccion)
    if not cambios:
        raise ValueError('Nada que cambiar')
    with candado, conectar() as con:
        if seccion is not None:
            # Se recuerda para la próxima vez que alguien agregue ese producto
            fila = con.execute('SELECT nombre FROM items WHERE id = ?', (item_id,)).fetchone()
            if fila:
                nombre = valores[cambios.index('nombre = ?')] if 'nombre = ?' in cambios else fila[0]
                con.execute('INSERT INTO secciones (clave, seccion) VALUES (?, ?) '
                            'ON CONFLICT(clave) DO UPDATE SET seccion = excluded.seccion', (clave(nombre), seccion))
        cur = con.execute(f'UPDATE items SET {", ".join(cambios)} WHERE id = ?', (*valores, item_id))
        if cur.rowcount:
            subir_version(con)
        return leer_todo(con)


def borrar(item_id):
    with candado, conectar() as con:
        if con.execute('DELETE FROM items WHERE id = ?', (item_id,)).rowcount:
            subir_version(con)
        return leer_todo(con)


def limpiar_comprados():
    with candado, conectar() as con:
        if con.execute('DELETE FROM items WHERE comprado = 1').rowcount:
            subir_version(con)
        return leer_todo(con)


def sugerencias():
    with conectar() as con:
        filas = con.execute(
            'SELECT nombre FROM historial ORDER BY veces DESC, ultima_vez DESC LIMIT 300'
        ).fetchall()
    return {'sugerencias': [f['nombre'] for f in filas]}


# ---------- HTTP ----------

RUTA_ITEM = re.compile(r'^/api/items/(\d+)$')


class Manejador(BaseHTTPRequestHandler):
    server_version = 'ListaCompras'

    def log_message(self, formato, *args):
        pass  # sin ruido en el journal por cada consulta

    def responder(self, codigo, datos):
        cuerpo = json.dumps(datos, ensure_ascii=False).encode('utf-8')
        self.send_response(codigo)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def leer_json(self):
        largo = int(self.headers.get('Content-Length') or 0)
        if largo > MAX_CUERPO:
            raise ValueError('Pedido demasiado grande')
        if not largo:
            return {}
        try:
            datos = json.loads(self.rfile.read(largo))
        except json.JSONDecodeError:
            raise ValueError('JSON inválido') from None
        if not isinstance(datos, dict):
            raise ValueError('Se esperaba un objeto JSON')
        return datos

    def atender(self, accion):
        try:
            self.responder(200, accion())
        except ValueError as e:
            self.responder(400, {'error': str(e)})
        except Exception as e:  # noqa: BLE001 - que el servicio no se caiga por un pedido
            print('Error:', repr(e), flush=True)
            self.responder(500, {'error': 'Error interno'})

    def do_GET(self):
        ruta = self.path.split('?')[0]
        if ruta == '/api/items':
            self.atender(lambda: leer_todo(conectar()))
        elif ruta == '/api/sugerencias':
            self.atender(sugerencias)
        elif ruta == '/api/secciones':
            self.atender(lambda: {'secciones': [{'nombre': n, 'icono': i} for n, i in SECCIONES]})
        else:
            self.responder(404, {'error': 'No existe'})

    def do_POST(self):
        ruta = self.path.split('?')[0]
        if ruta == '/api/items':
            self.atender(lambda: agregar(self.leer_json()))
        elif ruta == '/api/limpiar':
            self.atender(limpiar_comprados)
        else:
            self.responder(404, {'error': 'No existe'})

    def do_PATCH(self):
        m = RUTA_ITEM.match(self.path.split('?')[0])
        if m:
            self.atender(lambda: modificar(int(m.group(1)), self.leer_json()))
        else:
            self.responder(404, {'error': 'No existe'})

    def do_DELETE(self):
        m = RUTA_ITEM.match(self.path.split('?')[0])
        if m:
            self.atender(lambda: borrar(int(m.group(1))))
        else:
            self.responder(404, {'error': 'No existe'})


def main():
    preparar_bd()
    servidor = ThreadingHTTPServer((HOST, PUERTO), Manejador)
    print(f'Lista de compras en http://{HOST}:{PUERTO} (BD: {BD})', flush=True)
    servidor.serve_forever()


if __name__ == '__main__':
    main()
