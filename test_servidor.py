"""Pruebas del servidor de la lista: python3 -m unittest -v (usa una BD temporal)."""
import os
import tempfile
import unittest
from pathlib import Path

_tmp = tempfile.TemporaryDirectory()
os.environ['LISTA_BD'] = str(Path(_tmp.name) / 'prueba.db')
import servidor as s  # noqa: E402


class Funciones(unittest.TestCase):
    def test_clave_ignora_tildes_plural_y_parentesis(self):
        self.assertEqual(s.clave('Limón'), s.clave('limones'))
        self.assertEqual(s.clave('Chile'), s.clave('chiles'))
        self.assertEqual(s.clave('Nuez'), s.clave('nueces'))
        self.assertEqual(s.clave('Papas (unas 4 grandes)'), s.clave('papa'))
        self.assertNotEqual(s.clave('Papa'), s.clave('Papel'))

    def test_sumar_cantidades(self):
        casos = [('1/2', '8', '8 1/2'), ('1', '8', '9'), ('1 litro', '1 litro', '2 litros'), ('500 g', '250 gr', '750 g'),
                 ('1 lata', '1', '2 latas'), ('dos', '3', '5'), ('', '2', '2'), ('2', '', '2'), ('1,5 kg', '1 kg', '2 1/2 kg'),
                 ('1 kg', '2 bolsas', '1 kg + 2 bolsas'), ('500 g', '1', '500 g + 1')]
        for a, b, esperado in casos:
            with self.subTest(a=a, b=b):
                self.assertEqual(s.sumar_cantidades(a, b), esperado)

    def test_secciones(self):
        casos = {'Ajo en polvo': 'Especias', 'Ajo': 'Frutas y verduras', 'Chiles chipotles en adobo': 'Abarrotes',
                 'Jabón para trastes': 'Limpieza', 'Jabón': 'Higiene', 'Papel higiénico': 'Higiene',
                 'Agua mineral con gas': 'Bebidas', 'Huevos': 'Lácteos y huevos', 'Sellador de silicón': 'Otros'}
        for nombre, seccion in casos.items():
            with self.subTest(nombre=nombre):
                self.assertEqual(s.adivinar_seccion(nombre), seccion)


class Api(unittest.TestCase):
    def setUp(self):
        s.BD.unlink(missing_ok=True)
        s.preparar_bd()

    def pendientes(self, datos):
        return [(i['nombre'], i['cantidad']) for i in datos['items'] if not i['comprado']]

    def test_repetido_suma_en_vez_de_duplicar(self):
        s.agregar({'nombre': 'Limones', 'cantidad': '8'})
        d = s.agregar({'nombre': 'Limón', 'cantidad': '1'})
        self.assertEqual(self.pendientes(d), [('Limones', '9')])
        d = s.agregar({'nombre': 'mayonesa', 'cantidad': ''})
        d = s.agregar({'nombre': 'Mayonesa', 'cantidad': ''})
        self.assertEqual(len(self.pendientes(d)), 2)

    def test_comprado_no_se_suma(self):
        d = s.agregar({'nombre': 'Leche', 'cantidad': '1'})
        s.modificar(d['items'][0]['id'], {'comprado': True})
        d = s.agregar({'nombre': 'Leche', 'cantidad': '2'})
        self.assertEqual(self.pendientes(d), [('Leche', '2')])

    def test_editar_cantidad_y_seccion_se_recuerda(self):
        d = s.agregar({'nombre': 'Sellador de silicón', 'cantidad': '1'})
        item = d['items'][0]
        self.assertEqual(item['seccion'], 'Otros')
        d = s.modificar(item['id'], {'cantidad': '2 tubos', 'seccion': 'Limpieza'})
        self.assertEqual((d['items'][0]['cantidad'], d['items'][0]['seccion']), ('2 tubos', 'Limpieza'))
        s.borrar(item['id'])
        d = s.agregar({'nombre': 'selladores de silicon'})
        self.assertEqual(d['items'][0]['seccion'], 'Limpieza')
        with self.assertRaises(ValueError):
            s.modificar(d['items'][0]['id'], {'seccion': 'Inventada'})

    def test_migracion_llena_secciones(self):
        with s.conectar() as con:
            con.execute("INSERT INTO items (nombre, cantidad, seccion, creado) VALUES ('Tomate', '1', '', 'x')")
        s.preparar_bd()
        self.assertEqual(s.leer_todo(s.conectar())['items'][0]['seccion'], 'Frutas y verduras')


if __name__ == '__main__':
    unittest.main()
