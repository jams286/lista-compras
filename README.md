# lista-compras

Lista de compras compartida de la casa: todos agregan desde su celular y quien va al súper ve la lista completa. Los cambios llegan a los demás en unos segundos.

- Página: http://192.168.1.4/lista-compras/
- Datos: `~/.local/share/casa/lista-compras.db` (SQLite)

## Partes

- `web/`: página estática que se publica en `/var/www/lista-compras/`.
- `servidor.py`: API JSON (solo Python estándar + SQLite) en `127.0.0.1:8770`. nginx publica `/lista-compras/api/` → `/api/`.
- `servicio/lista-compras.service`: servicio systemd de usuario.

## Comandos

Publicar la página:

```
rsync -a --delete ~/proyectos/casa/lista-compras/web/ /var/www/lista-compras/
```

Instalar o actualizar el servicio:

```
mkdir -p ~/.config/systemd/user
cp ~/proyectos/casa/lista-compras/servicio/lista-compras.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now lista-compras.service
systemctl --user restart lista-compras.service   # después de cambiar servidor.py
```

Ver el log: `journalctl --user -u lista-compras -f`

Respaldo de los datos (seguro aunque el servicio esté corriendo):

```
python3 -c "import sqlite3,pathlib; o=sqlite3.connect(pathlib.Path.home()/'.local/share/casa/lista-compras.db'); d=sqlite3.connect('lista-compras-respaldo.db'); o.backup(d)"
```
