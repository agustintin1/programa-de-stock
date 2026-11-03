from contextlib import closing
import os
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


_TEMPORARY_DIRECTORY = tempfile.TemporaryDirectory()
_DATABASE_PATH = Path(_TEMPORARY_DIRECTORY.name) / 'legacy-stock.db'
_LEGACY_DATABASE = sqlite3.connect(_DATABASE_PATH)
_LEGACY_DATABASE.execute('''
    CREATE TABLE productos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        descripcion TEXT,
        precio REAL NOT NULL,
        stock INTEGER NOT NULL,
        categoria TEXT NOT NULL
    )
''')
_LEGACY_DATABASE.execute('''
    CREATE TABLE usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        usuario TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        rol TEXT NOT NULL CHECK (rol IN ('admin', 'operador')),
        creado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
''')
_LEGACY_DATABASE.execute('''
    CREATE TABLE ubicaciones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL UNIQUE,
        activa INTEGER NOT NULL DEFAULT 1,
        creada_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
''')
_LEGACY_DATABASE.execute('''
    CREATE TABLE existencias (
        producto_id INTEGER NOT NULL REFERENCES productos(id),
        ubicacion_id INTEGER NOT NULL REFERENCES ubicaciones(id),
        cantidad INTEGER NOT NULL DEFAULT 0 CHECK (cantidad >= 0),
        PRIMARY KEY (producto_id, ubicacion_id)
    )
''')
_LEGACY_DATABASE.execute('''
    CREATE TABLE movimientos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        producto_id INTEGER NOT NULL REFERENCES productos(id),
        ubicacion_id INTEGER NOT NULL REFERENCES ubicaciones(id),
        usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
        tipo TEXT NOT NULL,
        cantidad INTEGER NOT NULL CHECK (cantidad > 0),
        proveedor TEXT,
        nota TEXT,
        creado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
''')
_LEGACY_DATABASE.execute(
    'INSERT INTO productos VALUES (1, ?, ?, ?, ?, ?)',
    ('Producto anterior', 'Debe conservarse', 12.5, 9, 'Prueba'),
)
_LEGACY_DATABASE.execute(
    "INSERT INTO ubicaciones (id, nombre) VALUES (1, 'Depósito principal')"
)
_LEGACY_DATABASE.execute(
    'INSERT INTO existencias (producto_id, ubicacion_id, cantidad) '
    'VALUES (1, 1, 9)'
)
_LEGACY_DATABASE.commit()
_LEGACY_DATABASE.close()
os.environ['STOCK_DATABASE'] = str(_DATABASE_PATH)
os.environ.pop('STOCK_ADMIN_USERNAME', None)
os.environ.pop('STOCK_ADMIN_PASSWORD', None)

import app as inventario

aplicacion = inventario.app


class AdaptadorDeBaseDeDatosTest(unittest.TestCase):
  def test_ejecutar_adapta_placeholders_para_postgresql(self):
    class CursorDePrueba:
      sql = None
      parametros = None

      def execute(self, sql, parametros):
        self.sql = sql
        self.parametros = parametros

    cursor = CursorDePrueba()
    with (
        patch.object(inventario, 'database_url', 'postgresql://test'),
        patch.object(inventario, 'POSTGRES_DISPONIBLE', True),
    ):
      inventario.ejecutar(
          cursor,
          'INSERT INTO ubicaciones (nombre) VALUES (?)',
          ('Depósito principal',),
      )

    self.assertEqual(
        cursor.sql,
        'INSERT INTO ubicaciones (nombre) VALUES (%s)',
    )
    self.assertEqual(cursor.parametros, ('Depósito principal',))


class InventarioTest(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    aplicacion.config.update(TESTING=True, SECRET_KEY='clave-de-prueba')
    cls.cliente = aplicacion.test_client()

  @staticmethod
  def csrf(respuesta):
    coincidencia = re.search(
        rb'name="_csrf_token" value="([^"]+)"', respuesta.data
    )
    if not coincidencia:
      raise AssertionError('No se encontró el token CSRF en el formulario')
    return coincidencia.group(1).decode()

  def test_flujo_de_inventario_y_migracion(self):
    respuesta = self.cliente.get(
        '/configurar', environ_base={'REMOTE_ADDR': '192.0.2.10'}
    )
    self.assertEqual(respuesta.status_code, 403)

    respuesta = self.cliente.get('/configurar')
    self.assertEqual(respuesta.status_code, 200)
    respuesta = self.cliente.post('/configurar', data={
        '_csrf_token': self.csrf(respuesta),
        'nombre': 'Administradora',
        'usuario': 'admin',
        'password': 'UnaClaveLarga123!',
    }, follow_redirects=True)
    self.assertEqual(respuesta.status_code, 200)

    respuesta = self.cliente.get('/login')
    respuesta = self.cliente.post('/login', data={
        '_csrf_token': self.csrf(respuesta),
        'usuario': 'admin',
        'password': 'UnaClaveLarga123!',
    }, follow_redirects=True)
    self.assertIn('Hola, Administradora', respuesta.get_data(as_text=True))

    respuesta = self.cliente.get('/productos/nuevo')
    self.assertEqual(respuesta.status_code, 200)
    self.assertIn(
        'name="nombre"', respuesta.get_data(as_text=True)
    )

    respuesta = self.cliente.get('/productos')
    self.assertIn('Producto anterior', respuesta.get_data(as_text=True))
    token = self.csrf(respuesta)
    with closing(sqlite3.connect(_DATABASE_PATH)) as conexion:
      deposito = conexion.execute(
          "SELECT id FROM ubicaciones WHERE nombre = 'Depósito principal'"
      ).fetchone()[0]

    def registrar(tipo, cantidad, ubicacion=deposito, proveedor=''):
      return self.cliente.post('/movimientos', data={
          '_csrf_token': token,
          'producto_id': '1',
          'ubicacion_id': str(ubicacion),
          'tipo': tipo,
          'cantidad': str(cantidad),
          'proveedor': proveedor,
          'nota': '',
      }, follow_redirects=True)

    respuesta = registrar('venta', 4)
    self.assertIn('Movimiento guardado', respuesta.get_data(as_text=True))
    respuesta = registrar('venta', 6)
    self.assertIn('No hay suficiente stock', respuesta.get_data(as_text=True))
    respuesta = registrar('compra', 3, proveedor='Proveedor de prueba')
    self.assertIn('Movimiento guardado', respuesta.get_data(as_text=True))

    with closing(sqlite3.connect(_DATABASE_PATH)) as conexion:
      stock = conexion.execute(
          'SELECT cantidad FROM existencias '
          'WHERE producto_id = 1 AND ubicacion_id = 1'
      ).fetchone()[0]
      stock_compatible = conexion.execute(
          'SELECT stock FROM productos WHERE id = 1'
      ).fetchone()[0]
      cantidad_movimientos = conexion.execute(
          'SELECT COUNT(*) FROM movimientos'
      ).fetchone()[0]
    self.assertEqual((stock, stock_compatible, cantidad_movimientos), (8, 8, 2))

    respuesta = self.cliente.post('/ubicaciones', data={
        '_csrf_token': token, 'nombre': 'Sucursal Centro',
    }, follow_redirects=True)
    self.assertIn('Ubicación creada', respuesta.get_data(as_text=True))
    with closing(sqlite3.connect(_DATABASE_PATH)) as conexion:
      sucursal = conexion.execute(
          "SELECT id FROM ubicaciones WHERE nombre = 'Sucursal Centro'"
      ).fetchone()[0]
    respuesta = registrar('compra', 2, sucursal, 'Proveedor local')
    self.assertIn('Movimiento guardado', respuesta.get_data(as_text=True))

    respuesta = self.cliente.get('/reportes/movimientos.csv')
    self.assertIn('Proveedor local', respuesta.get_data(as_text=True))
    respuesta = self.cliente.post('/productos/nuevo', data={
        '_csrf_token': token,
        'nombre': 'Producto con código',
        'descripcion': '',
        'precio': '7.50',
        'stock': '0',
        'stock_minimo': '2',
        'categoria': 'Prueba',
        'codigo_barras': '123456789',
        'ubicacion_id': str(deposito),
    }, follow_redirects=True)
    self.assertIn('Producto creado', respuesta.get_data(as_text=True))
    respuesta = self.cliente.post('/productos/nuevo', data={
        '_csrf_token': token,
        'nombre': 'Código repetido',
        'descripcion': '',
        'precio': '4.00',
        'stock': '0',
        'stock_minimo': '2',
        'categoria': 'Prueba',
        'codigo_barras': '123456789',
        'ubicacion_id': str(deposito),
    }, follow_redirects=True)
    self.assertIn(
        'Ese código de barras ya está registrado.',
        respuesta.get_data(as_text=True),
    )
    with closing(sqlite3.connect(_DATABASE_PATH)) as conexion:
      productos_activos = conexion.execute(
          "SELECT COUNT(*) FROM productos WHERE nombre IN "
          "('Producto con código', 'Código repetido') AND activo = TRUE"
      ).fetchone()[0]
      self.assertEqual(productos_activos, 1)

    respuesta = self.cliente.post(
        '/productos/eliminar/1',
        data={'_csrf_token': token},
        follow_redirects=True,
    )
    self.assertIn(
        'No se puede archivar un producto con stock',
        respuesta.get_data(as_text=True),
    )
    self.assertEqual(
        self.cliente.post('/productos/eliminar/1').status_code, 400
    )
    respuesta = self.cliente.get('/')
    self.assertIn('Un ojito a estas cositas', respuesta.get_data(as_text=True))
    self.assertIn('Producto anterior', respuesta.get_data(as_text=True))
    self.assertIn('Producto con código', respuesta.get_data(as_text=True))

    respuesta = self.cliente.get('/usuarios')
    token = self.csrf(respuesta)
    respuesta = self.cliente.post('/usuarios', data={
        '_csrf_token': token,
        'nombre': 'Operador',
        'usuario': 'operador',
        'password': 'OtraClaveLarga123!',
        'rol': 'operador',
    }, follow_redirects=True)
    self.assertIn('Usuario creado', respuesta.get_data(as_text=True))
    self.cliente.post('/salir', data={'_csrf_token': token})

    respuesta = self.cliente.get('/login')
    respuesta = self.cliente.post('/login', data={
        '_csrf_token': self.csrf(respuesta),
        'usuario': 'operador',
        'password': 'OtraClaveLarga123!',
    }, follow_redirects=True)
    self.assertIn('Hola, Operador', respuesta.get_data(as_text=True))
    self.assertEqual(self.cliente.get('/usuarios').status_code, 403)
    self.assertEqual(
        self.cliente.post('/productos/eliminar/1').status_code, 400
    )

    respuesta = self.cliente.get('/registro')
    respuesta = self.cliente.post('/registro', data={
        '_csrf_token': self.csrf(respuesta),
        'empresa': 'Mascotas Norte',
        'nombre': 'Administradora nueva',
        'usuario': 'admin_dos',
        'password': 'OtraClaveSegura456!',
    }, follow_redirects=True)
    self.assertIn('¡El espacio de Mascotas Norte ya está listo!', respuesta.get_data(as_text=True))
    self.assertNotIn('Producto anterior', self.cliente.get('/productos').get_data(as_text=True))

    with closing(sqlite3.connect(_DATABASE_PATH)) as conexion:
      empresa_original = conexion.execute(
          "SELECT id FROM empresas WHERE clave = 'empresa-inicial'"
      ).fetchone()[0]
      empresa_nueva = conexion.execute(
          "SELECT id FROM empresas WHERE nombre = 'Mascotas Norte'"
      ).fetchone()[0]
      deposito_nuevo = conexion.execute(
          'SELECT id FROM ubicaciones '
          'WHERE empresa_id = ? AND nombre = ?',
          (empresa_nueva, 'Depósito principal'),
      ).fetchone()[0]
    self.assertNotEqual(empresa_original, empresa_nueva)

    respuesta = self.cliente.get('/productos/nuevo')
    respuesta = self.cliente.post('/productos/nuevo', data={
        '_csrf_token': self.csrf(respuesta),
        'nombre': 'Alimento para perros',
        'descripcion': '',
        'precio': '7.50',
        'stock': '3',
        'stock_minimo': '2',
        'categoria': 'Mascotas',
        'codigo_barras': '123456789',
        'ubicacion_id': str(deposito_nuevo),
    }, follow_redirects=True)
    self.assertIn('Producto creado', respuesta.get_data(as_text=True))
    self.assertIn('Alimento para perros', self.cliente.get('/productos').get_data(as_text=True))

    respuesta = self.cliente.get('/usuarios')
    usuarios_nuevos = respuesta.get_data(as_text=True)
    self.assertIn('admin_dos', usuarios_nuevos)
    self.assertNotRegex(usuarios_nuevos, r'<td>\s*operador\s*</td>')

    respuesta = self.cliente.get('/movimientos')
    respuesta = self.cliente.post('/movimientos', data={
        '_csrf_token': self.csrf(respuesta),
        'producto_id': '1',
        'ubicacion_id': str(deposito_nuevo),
        'tipo': 'venta',
        'cantidad': '1',
        'proveedor': '',
        'nota': '',
    }, follow_redirects=True)
    self.assertIn('Selecciona un producto activo.', respuesta.get_data(as_text=True))
    respuesta = self.cliente.get(
        '/productos/editar/1', follow_redirects=True
    )
    self.assertIn('El producto no existe o fue archivado.', respuesta.get_data(as_text=True))
    respuesta = self.cliente.get('/productos')
    respuesta = self.cliente.post(
        '/productos/eliminar/1',
        data={'_csrf_token': self.csrf(respuesta)},
        follow_redirects=True,
    )
    self.assertIn('El producto no existe o ya fue archivado.', respuesta.get_data(as_text=True))

    respuesta = self.cliente.get('/reportes/movimientos.csv')
    reporte = respuesta.get_data(as_text=True)
    self.assertIn('Alimento para perros', reporte)
    self.assertNotIn('Producto anterior', reporte)

    respuesta = self.cliente.get('/registro')
    respuesta = self.cliente.post('/registro', data={
        '_csrf_token': self.csrf(respuesta),
        'empresa': 'No debe crearse',
        'nombre': 'Otra administradora',
        'usuario': 'admin',
        'password': 'OtraClaveSegura789!',
    }, follow_redirects=True)
    self.assertIn('Ese nombre de usuario ya está en uso.', respuesta.get_data(as_text=True))

    inventario.inicializar_base_datos()
    with closing(sqlite3.connect(_DATABASE_PATH)) as conexion:
      producto_nuevo = conexion.execute(
          'SELECT id FROM productos '
          'WHERE empresa_id = ? AND nombre = ?',
          (empresa_nueva, 'Alimento para perros'),
      ).fetchone()
      cantidad_empresas = conexion.execute(
          'SELECT COUNT(*) FROM empresas'
      ).fetchone()[0]
      stock_original = conexion.execute(
          'SELECT cantidad FROM existencias '
          'WHERE producto_id = 1 AND ubicacion_id = 1'
      ).fetchone()[0]
      stock_nuevo = conexion.execute(
          'SELECT cantidad FROM existencias '
          'WHERE producto_id = ? AND ubicacion_id = ?',
          (producto_nuevo[0], deposito_nuevo),
      ).fetchone()[0]
      cantidad_movimientos_nuevos = conexion.execute(
          'SELECT COUNT(*) FROM movimientos WHERE empresa_id = ?',
          (empresa_nueva,),
      ).fetchone()[0]
      producto_original_activo = conexion.execute(
          'SELECT activo FROM productos WHERE id = 1'
      ).fetchone()[0]
      errores_foraneos = conexion.execute(
          'PRAGMA foreign_key_check'
      ).fetchall()
    self.assertEqual(cantidad_empresas, 2)
    self.assertEqual(stock_original, 8)
    self.assertEqual(stock_nuevo, 3)
    self.assertEqual(cantidad_movimientos_nuevos, 1)
    self.assertEqual(producto_original_activo, 1)
    self.assertEqual(errores_foraneos, [])


if __name__ == '__main__':
  unittest.main()
