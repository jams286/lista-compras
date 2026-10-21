"""Servicio de la lista de compras: API JSON sobre SQLite.

Escucha solo en 127.0.0.1; nginx publica /lista-compras/api/ -> /api/.
Sin dependencias externas (solo la biblioteca estándar).

    python3 servidor.py

Rutas:
    GET    /api/items             lista completa + versión
    POST   /api/items             {"nombre", "cantidad"}  agrega (o actualiza si ya está pendiente)
    PATCH  /api/items/<id>        {"comprado"?, "nombre"?, "cantidad"?}
    DELETE /api/items/<id>
    POST   /api/limpiar           borra los comprados
    GET    /api/sugerencias       nombres usados antes, los más frecuentes primero
"""

import json
import os
import re
import sqlite3
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = '127.0.0.1'
# Se pueden cambiar para pruebas sin tocar los datos reales
PUERTO = int(os.environ.get('LISTA_PUERTO', 8770))
BD = Path(os.environ.get('LISTA_BD', Path.home() / '.local/share/casa/lista-compras.db'))
MAX_CUERPO = 4096
MAX_NOMBRE, MAX_CANTIDAD = 60, 20

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
            INSERT OR IGNORE INTO meta (clave, valor) VALUES ('version', 0);
        ''')


def ahora():
    return datetime.now().isoformat(timespec='seconds')


def subir_version(con):
    con.execute("UPDATE meta SET valor = valor + 1 WHERE clave = 'version'")


def leer_todo(con):
    version = con.execute("SELECT valor FROM meta WHERE clave = 'version'").fetchone()[0]
    filas = con.execute('''
        SELECT id, nombre, cantidad, comprado, creado, comprado_en FROM items
        ORDER BY comprado, CASE WHEN comprado THEN comprado_en END DESC, id
    ''').fetchall()
    items = [dict(f, comprado=bool(f['comprado'])) for f in filas]
    return {'version': version, 'items': items}


def limpiar_texto(valor, maximo):
    if not isinstance(valor, str):
        return ''
    return re.sub(r'\s+', ' ', valor).strip()[:maximo]


# ---------- Operaciones ----------

def agregar(datos):
    nombre = limpiar_texto(datos.get('nombre'), MAX_NOMBRE)
    cantidad = limpiar_texto(datos.get('cantidad'), MAX_CANTIDAD)
    if not nombre:
        raise ValueError('Falta el nombre')
    with candado, conectar() as con:
        # Si ya está pendiente con el mismo nombre, solo se actualiza la cantidad
        existente = con.execute(
            'SELECT id FROM items WHERE comprado = 0 AND lower(nombre) = lower(?)', (nombre,)
        ).fetchone()
        if existente:
            if cantidad:
                con.execute('UPDATE items SET cantidad = ? WHERE id = ?', (cantidad, existente['id']))
        else:
            con.execute('INSERT INTO items (nombre, cantidad, creado) VALUES (?, ?, ?)',
                        (nombre, cantidad, ahora()))
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
    if not cambios:
        raise ValueError('Nada que cambiar')
    with candado, conectar() as con:
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
