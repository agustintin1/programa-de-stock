import ipaddress
import os
import secrets
import sqlite3
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from functools import wraps

from flask import (
    Flask,
    Response,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

try:
  import psycopg2
  import psycopg2.extras

  POSTGRES_DISPONIBLE = True
except ImportError:
  POSTGRES_DISPONIBLE = False

ERRORES_INTEGRIDAD = (sqlite3.IntegrityError,) + (
    (psycopg2.IntegrityError,) if POSTGRES_DISPONIBLE else ()
)


app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=os.environ.get('COOKIE_SECURE') == '1',
)

database_url = os.environ.get('DATABASE_URL')
if database_url and database_url.startswith('postgres://'):
  database_url = database_url.replace('postgres://', 'postgresql://', 1)


def es_postgres():
  if database_url and not POSTGRES_DISPONIBLE:
    raise RuntimeError(
        'DATABASE_URL está configurada, pero falta instalar psycopg2-binary.'
    )
  return bool(database_url)


@contextmanager
def obtener_conexion():
  postgres = es_postgres()
  if postgres:
    conexion = psycopg2.connect(
        database_url, cursor_factory=psycopg2.extras.DictCursor
    )
  else:
    ruta_db = os.environ.get('STOCK_DATABASE', 'stock.db')
    conexion = sqlite3.connect(ruta_db)
    conexion.row_factory = sqlite3.Row
    conexion.execute('PRAGMA foreign_keys = ON')

  try:
    yield conexion
    conexion.commit()
  except Exception:
    conexion.rollback()
    raise
  finally:
    conexion.close()


def ejecutar(cursor, sql, parametros=()):
  if es_postgres():
    sql = sql.replace('?', '%s')
  cursor.execute(sql, parametros)


def columnas_de(cursor, tabla):
  if es_postgres():
    ejecutar(
        cursor,
        '''
        SELECT column_name FROM information_schema.columns
        WHERE table_name = ?
        ''',
        (tabla,),
    )
    return {fila['column_name'] for fila in cursor.fetchall()}
  ejecutar(cursor, f'PRAGMA table_info({tabla})')
  return {fila['name'] for fila in cursor.fetchall()}


def quitar_unicidad_global_de_ubicaciones_sqlite():
  ruta_db = os.environ.get('STOCK_DATABASE', 'stock.db')
  conexion = sqlite3.connect(ruta_db)
  conexion.row_factory = sqlite3.Row
  try:
    conexion.execute('PRAGMA foreign_keys = OFF')
    indices = conexion.execute('PRAGMA index_list(ubicaciones)').fetchall()
    indice_nombre_unico = None
    for indice in indices:
      if not indice['unique']:
        continue
      columnas = conexion.execute(
          f'PRAGMA index_info("{indice["name"]}")'
      ).fetchall()
      if [columna['name'] for columna in columnas] == ['nombre']:
        indice_nombre_unico = indice['name']
        break

    if not indice_nombre_unico:
      return

    columnas = {
        fila['name']
        for fila in conexion.execute('PRAGMA table_info(ubicaciones)').fetchall()
    }
    empresa_columna = (
        'empresa_id INTEGER REFERENCES empresas(id)'
        if 'empresa_id' in columnas else 'empresa_id INTEGER'
    )
    conexion.execute(f'''
      CREATE TABLE ubicaciones_nueva (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        activa INTEGER NOT NULL DEFAULT 1,
        creada_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        {empresa_columna}
      )
    ''')
    conexion.execute('''
      INSERT INTO ubicaciones_nueva (id, nombre, activa, creada_en, empresa_id)
      SELECT id, nombre, activa, creada_en, empresa_id FROM ubicaciones
    ''')
    conexion.execute('DROP TABLE ubicaciones')
    conexion.execute('ALTER TABLE ubicaciones_nueva RENAME TO ubicaciones')
    conexion.commit()
  except Exception:
    conexion.rollback()
    raise
  finally:
    conexion.close()


def inicializar_base_datos():
  postgres = es_postgres()
  with obtener_conexion() as conexion:
    cursor = conexion.cursor()
    if postgres:
      cursor.execute('''
        CREATE TABLE IF NOT EXISTS empresas (
          id SERIAL PRIMARY KEY,
          nombre VARCHAR(120) NOT NULL,
          clave VARCHAR(24) NOT NULL UNIQUE,
          creada_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
      ''')
      cursor.execute('''
        CREATE TABLE IF NOT EXISTS productos (
          id SERIAL PRIMARY KEY,
          nombre VARCHAR(150) NOT NULL,
          descripcion TEXT,
          precio NUMERIC(10, 2) NOT NULL,
          stock INTEGER NOT NULL DEFAULT 0,
          categoria VARCHAR(100) NOT NULL
        )
      ''')
      cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
          id SERIAL PRIMARY KEY,
          nombre VARCHAR(120) NOT NULL,
          usuario VARCHAR(80) NOT NULL UNIQUE,
          password_hash TEXT NOT NULL,
          rol VARCHAR(20) NOT NULL CHECK (rol IN ('admin', 'operador')),
          creado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
      ''')
      cursor.execute('''
        CREATE TABLE IF NOT EXISTS ubicaciones (
          id SERIAL PRIMARY KEY,
          nombre VARCHAR(120) NOT NULL,
          activa BOOLEAN NOT NULL DEFAULT TRUE,
          creada_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
      ''')
      cursor.execute('''
        CREATE TABLE IF NOT EXISTS existencias (
          producto_id INTEGER NOT NULL REFERENCES productos(id),
          ubicacion_id INTEGER NOT NULL REFERENCES ubicaciones(id),
          cantidad INTEGER NOT NULL DEFAULT 0 CHECK (cantidad >= 0),
          PRIMARY KEY (producto_id, ubicacion_id)
        )
      ''')
      cursor.execute('''
        CREATE TABLE IF NOT EXISTS movimientos (
          id SERIAL PRIMARY KEY,
          producto_id INTEGER NOT NULL REFERENCES productos(id),
          ubicacion_id INTEGER NOT NULL REFERENCES ubicaciones(id),
          usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
          tipo VARCHAR(30) NOT NULL,
          cantidad INTEGER NOT NULL CHECK (cantidad > 0),
          proveedor VARCHAR(160),
          nota TEXT,
          creado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
      ''')
    else:
      cursor.execute('''
        CREATE TABLE IF NOT EXISTS empresas (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          nombre TEXT NOT NULL,
          clave TEXT NOT NULL UNIQUE,
          creada_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
      ''')
      cursor.execute('''
        CREATE TABLE IF NOT EXISTS productos (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          nombre TEXT NOT NULL,
          descripcion TEXT,
          precio REAL NOT NULL,
          stock INTEGER NOT NULL DEFAULT 0,
          categoria TEXT NOT NULL
        )
      ''')
      cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          nombre TEXT NOT NULL,
          usuario TEXT NOT NULL UNIQUE,
          password_hash TEXT NOT NULL,
          rol TEXT NOT NULL CHECK (rol IN ('admin', 'operador')),
          creado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
      ''')
      cursor.execute('''
        CREATE TABLE IF NOT EXISTS ubicaciones (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          nombre TEXT NOT NULL,
          activa INTEGER NOT NULL DEFAULT 1,
          creada_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
      ''')
      cursor.execute('''
        CREATE TABLE IF NOT EXISTS existencias (
          producto_id INTEGER NOT NULL REFERENCES productos(id),
          ubicacion_id INTEGER NOT NULL REFERENCES ubicaciones(id),
          cantidad INTEGER NOT NULL DEFAULT 0 CHECK (cantidad >= 0),
          PRIMARY KEY (producto_id, ubicacion_id)
        )
      ''')
      cursor.execute('''
        CREATE TABLE IF NOT EXISTS movimientos (
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

    ejecutar(
        cursor,
        '''
        INSERT INTO empresas (nombre, clave)
        VALUES (?, 'empresa-inicial')
        ON CONFLICT (clave) DO NOTHING
        ''',
        (os.environ.get('STOCK_DEFAULT_COMPANY_NAME', 'Mi empresa')[:120],),
    )
    ejecutar(
        cursor,
        "SELECT id FROM empresas WHERE clave = 'empresa-inicial'",
    )
    empresa_inicial_id = cursor.fetchone()['id']

    for tabla in ('productos', 'usuarios', 'ubicaciones', 'existencias', 'movimientos'):
      columnas = columnas_de(cursor, tabla)
      if 'empresa_id' not in columnas:
        cursor.execute(
            f'ALTER TABLE {tabla} ADD COLUMN empresa_id INTEGER '
            'REFERENCES empresas(id)'
        )
      ejecutar(
          cursor,
          f'UPDATE {tabla} SET empresa_id = ? WHERE empresa_id IS NULL',
          (empresa_inicial_id,),
      )

    columnas = columnas_de(cursor, 'productos')
    columnas_nuevas = {
        'codigo_barras': 'TEXT' if not postgres else 'VARCHAR(80)',
        'stock_minimo': 'INTEGER NOT NULL DEFAULT 5',
        'activo': 'INTEGER NOT NULL DEFAULT 1' if not postgres else
        'BOOLEAN NOT NULL DEFAULT TRUE',
    }
    for nombre, tipo in columnas_nuevas.items():
      if nombre not in columnas:
        cursor.execute(f'ALTER TABLE productos ADD COLUMN {nombre} {tipo}')

    cursor.execute('DROP INDEX IF EXISTS idx_productos_codigo_barras')

    if postgres:
      cursor.execute(
          'ALTER TABLE ubicaciones '
          'DROP CONSTRAINT IF EXISTS ubicaciones_nombre_key'
      )

  if not postgres:
    quitar_unicidad_global_de_ubicaciones_sqlite()

  with obtener_conexion() as conexion:
    cursor = conexion.cursor()
    cursor.execute(
        'CREATE UNIQUE INDEX IF NOT EXISTS idx_productos_empresa_codigo_barras '
        'ON productos(empresa_id, codigo_barras) WHERE codigo_barras IS NOT NULL'
    )
    cursor.execute(
        'CREATE UNIQUE INDEX IF NOT EXISTS idx_ubicaciones_empresa_nombre '
        'ON ubicaciones(empresa_id, nombre)'
    )
    for tabla in ('productos', 'usuarios', 'ubicaciones', 'existencias', 'movimientos'):
      cursor.execute(
          f'CREATE INDEX IF NOT EXISTS idx_{tabla}_empresa '
          f'ON {tabla}(empresa_id)'
      )
    cursor.execute(
        'CREATE INDEX IF NOT EXISTS idx_movimientos_fecha '
        'ON movimientos(creado_en)'
    )
    ejecutar(
        cursor,
        '''
        INSERT INTO ubicaciones (nombre, empresa_id)
        VALUES (?, ?) ON CONFLICT (empresa_id, nombre) DO NOTHING
        ''',
        ('Depósito principal', empresa_inicial_id),
    )
    ejecutar(
        cursor,
        '''
        INSERT INTO existencias
          (producto_id, ubicacion_id, cantidad, empresa_id)
        SELECT p.id, u.id, p.stock, p.empresa_id
        FROM productos p CROSS JOIN ubicaciones u
        WHERE u.empresa_id = ? AND u.nombre = ? AND p.empresa_id = ?
          AND NOT EXISTS (
            SELECT 1 FROM existencias e
            WHERE e.producto_id = p.id AND e.ubicacion_id = u.id
          )
        ''',
        (
            empresa_inicial_id,
            'Depósito principal',
            empresa_inicial_id,
        ),
    )

    admin_usuario = os.environ.get('STOCK_ADMIN_USERNAME')
    admin_password = os.environ.get('STOCK_ADMIN_PASSWORD')
    if admin_usuario or admin_password:
      if not admin_usuario or not admin_password or len(admin_password) < 12:
        raise RuntimeError(
            'Para crear el administrador inicial, configura '
            'STOCK_ADMIN_USERNAME y STOCK_ADMIN_PASSWORD (12 caracteres mínimo).'
        )
      ejecutar(
          cursor,
          '''
          INSERT INTO usuarios
            (nombre, usuario, password_hash, rol, empresa_id)
          VALUES (?, ?, ?, 'admin', ?) ON CONFLICT (usuario) DO NOTHING
          ''',
          (
              admin_usuario.strip(),
              admin_usuario.strip(),
              generate_password_hash(admin_password),
              empresa_inicial_id,
          ),
      )


inicializar_base_datos()


def token_csrf():
  if '_csrf_token' not in session:
    session['_csrf_token'] = secrets.token_urlsafe(32)
  return session['_csrf_token']


@app.before_request
def validar_csrf():
  if request.method == 'POST':
    token = request.form.get('_csrf_token') or request.headers.get(
        'X-CSRF-Token'
    )
    if not token or not secrets.compare_digest(token, token_csrf()):
      abort(400, description='El formulario venció. Actualiza la página.')


@app.context_processor
def datos_comunes():
  return {
      'usuario_actual': session.get('usuario'),
      'empresa_actual': session.get('empresa'),
      'rol_actual': session.get('rol'),
      'csrf_token': token_csrf,
  }


def cargar_empresa_de_usuario():
  if session.get('empresa_id'):
    return True
  usuario_id = session.get('usuario_id')
  if not usuario_id:
    return False
  with obtener_conexion() as conexion:
    cursor = conexion.cursor()
    ejecutar(
        cursor,
        '''
        SELECT e.id, e.nombre
        FROM usuarios u JOIN empresas e ON e.id = u.empresa_id
        WHERE u.id = ?
        ''',
        (usuario_id,),
    )
    empresa = cursor.fetchone()
  if not empresa:
    session.clear()
    return False
  session['empresa_id'] = empresa['id']
  session['empresa'] = empresa['nombre']
  return True


def iniciar_sesion(usuario):
  session.clear()
  session['usuario_id'] = usuario['id']
  session['usuario'] = usuario['nombre']
  session['rol'] = usuario['rol']
  session['empresa_id'] = usuario['empresa_id']
  session['empresa'] = usuario['empresa_nombre']
  token_csrf()


def requiere_login(funcion):
  @wraps(funcion)
  def protegida(*args, **kwargs):
    if not session.get('usuario_id') or not cargar_empresa_de_usuario():
      return redirect(url_for('login', siguiente=request.path))
    return funcion(*args, **kwargs)

  return protegida


def requiere_admin(funcion):
  @wraps(funcion)
  def protegida(*args, **kwargs):
    if not session.get('usuario_id') or not cargar_empresa_de_usuario():
      return redirect(url_for('login', siguiente=request.path))
    if session.get('rol') != 'admin':
      abort(403)
    return funcion(*args, **kwargs)

  return protegida


def es_local():
  try:
    return ipaddress.ip_address(request.remote_addr or '').is_loopback
  except ValueError:
    return False


def obtener_ubicaciones(cursor, solo_activas=True):
  filtro = 'AND activa = TRUE' if solo_activas else ''
  ejecutar(
      cursor,
      'SELECT id, nombre FROM ubicaciones '
      'WHERE empresa_id = ? ' + filtro + ' ORDER BY nombre',
      (session['empresa_id'],),
  )
  return cursor.fetchall()


def validar_cantidad(valor):
  try:
    cantidad = int(valor)
    if cantidad < 1 or cantidad > 2147483647:
      raise ValueError
    return cantidad
  except (TypeError, ValueError):
    raise ValueError(
        'La cantidad debe ser un entero entre 1 y 2.147.483.647.'
    )


def validar_entero_no_negativo(valor, campo):
  try:
    numero = int(valor)
    if numero < 0 or numero > 2147483647:
      raise ValueError
    return numero
  except (TypeError, ValueError):
    raise ValueError(
        f'{campo} debe ser un entero entre 0 y 2.147.483.647.'
    )


def validar_precio(valor):
  try:
    precio = Decimal(valor)
    if (
        not precio.is_finite()
        or precio < 0
        or precio > Decimal('99999999.99')
    ):
      raise InvalidOperation
    return precio
  except (InvalidOperation, TypeError, ValueError):
    raise ValueError(
        'El precio debe estar entre 0 y 99.999.999,99.'
    )


def registrar_movimiento(
    cursor, producto_id, ubicacion_id, usuario_id, tipo, cantidad,
    empresa_id, proveedor='', nota=''
):
  entrada = tipo in ('compra', 'ajuste_entrada', 'inicial')
  if entrada:
    ejecutar(
        cursor,
        '''
        INSERT INTO existencias (producto_id, ubicacion_id, cantidad, empresa_id)
        VALUES (?, ?, ?, ?) ON CONFLICT (producto_id, ubicacion_id)
        DO UPDATE SET cantidad = existencias.cantidad + excluded.cantidad
        ''',
        (producto_id, ubicacion_id, cantidad, empresa_id),
    )
  else:
    ejecutar(
        cursor,
        '''
        UPDATE existencias SET cantidad = cantidad - ?
        WHERE producto_id = ? AND ubicacion_id = ? AND empresa_id = ?
          AND cantidad >= ?
        ''',
        (cantidad, producto_id, ubicacion_id, empresa_id, cantidad),
    )
    if cursor.rowcount != 1:
      raise ValueError('No hay suficiente stock en esa ubicación.')

  ejecutar(
      cursor,
      '''
      INSERT INTO movimientos
        (producto_id, ubicacion_id, usuario_id, tipo, cantidad, proveedor, nota,
         empresa_id)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?)
      ''',
      (
          producto_id,
          ubicacion_id,
          usuario_id,
          tipo,
          cantidad,
          proveedor.strip() or None,
          nota.strip() or None,
          empresa_id,
      ),
  )
  ejecutar(
      cursor,
      '''
      UPDATE productos SET stock = (
        SELECT COALESCE(SUM(cantidad), 0) FROM existencias
        WHERE producto_id = ? AND empresa_id = ?
      ) WHERE id = ? AND empresa_id = ?
      ''',
      (producto_id, empresa_id, producto_id, empresa_id),
  )


@app.route('/configurar', methods=['GET', 'POST'])
def configurar():
  with obtener_conexion() as conexion:
    cursor = conexion.cursor()
    ejecutar(cursor, 'SELECT COUNT(*) AS total FROM usuarios')
    if cursor.fetchone()['total']:
      return redirect(url_for('login'))

    if not es_local():
      abort(
          403,
          description='El administrador inicial solo se puede crear desde la computadora del servidor.',
      )

    if request.method == 'POST':
      nombre = request.form.get('nombre', '').strip()
      usuario = request.form.get('usuario', '').strip()
      password = request.form.get('password', '')
      if (
          not nombre or len(nombre) > 120
          or len(usuario) < 3 or len(usuario) > 80
          or len(password) < 12
      ):
        flash(
            'Completa tu nombre, usa un usuario de 3 caracteres y una '
            'contraseña de al menos 12 caracteres.',
            'error',
        )
      else:
        ejecutar(
            cursor,
            "SELECT id, nombre FROM empresas WHERE clave = 'empresa-inicial'",
        )
        empresa = cursor.fetchone()
        ejecutar(
            cursor,
            '''
            INSERT INTO usuarios
              (nombre, usuario, password_hash, rol, empresa_id)
            VALUES (?, ?, ?, 'admin', ?)
            ''',
            (
                nombre,
                usuario,
                generate_password_hash(password),
                empresa['id'],
            ),
        )
        iniciar_sesion({
            'id': cursor.lastrowid if not es_postgres() else 0,
            'nombre': nombre,
            'usuario': usuario,
            'rol': 'admin',
            'empresa_id': empresa['id'],
            'empresa_nombre': empresa['nombre'],
        })
        if es_postgres():
          ejecutar(cursor, 'SELECT id FROM usuarios WHERE usuario = ?', (usuario,))
          session['usuario_id'] = cursor.fetchone()['id']
        flash('Administrador creado. Ya puedes iniciar sesión.', 'success')
        return redirect(url_for('index'))

  return render_template('configurar.html')


@app.route('/registro', methods=['GET', 'POST'])
def registro():
  if request.method == 'POST':
    empresa_nombre = request.form.get('empresa', '').strip()
    nombre = request.form.get('nombre', '').strip()
    usuario = request.form.get('usuario', '').strip()
    password = request.form.get('password', '')
    if (
        not empresa_nombre or len(empresa_nombre) > 120
        or not nombre or len(nombre) > 120
        or len(usuario) < 3 or len(usuario) > 80
        or len(password) < 12
    ):
      flash(
          'Completa el negocio y tu nombre; el usuario debe tener '
          '3 caracteres y la contraseña 12 como mínimo.',
          'error',
      )
    else:
      try:
        with obtener_conexion() as conexion:
          cursor = conexion.cursor()
          clave_empresa = secrets.token_hex(12)
          ejecutar(
              cursor,
              '''
              INSERT INTO empresas (nombre, clave) VALUES (?, ?)
              ''' + (' RETURNING id' if es_postgres() else ''),
              (empresa_nombre, clave_empresa),
          )
          empresa_id = (
              cursor.fetchone()['id'] if es_postgres() else cursor.lastrowid
          )
          ejecutar(
              cursor,
              '''
              INSERT INTO ubicaciones (nombre, empresa_id)
              VALUES ('Depósito principal', ?)
              ''',
              (empresa_id,),
          )
          ejecutar(
              cursor,
              '''
              INSERT INTO usuarios
                (nombre, usuario, password_hash, rol, empresa_id)
              VALUES (?, ?, ?, 'admin', ?)
              ''' + (' RETURNING id' if es_postgres() else ''),
              (
                  nombre,
                  usuario,
                  generate_password_hash(password),
                  empresa_id,
              ),
          )
          usuario_id = (
              cursor.fetchone()['id'] if es_postgres() else cursor.lastrowid
          )
        iniciar_sesion({
            'id': usuario_id,
            'nombre': nombre,
            'usuario': usuario,
            'rol': 'admin',
            'empresa_id': empresa_id,
            'empresa_nombre': empresa_nombre,
        })
        flash(f'¡El espacio de {empresa_nombre} ya está listo!', 'success')
        return redirect(url_for('index'))
      except ERRORES_INTEGRIDAD:
        flash(
            'Ese nombre de usuario ya está en uso. Elige otro y prueba de nuevo.',
            'error',
        )
  return render_template('registro.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
  with obtener_conexion() as conexion:
    cursor = conexion.cursor()
    ejecutar(cursor, 'SELECT COUNT(*) AS total FROM usuarios')
    if not cursor.fetchone()['total']:
      return redirect(url_for('configurar'))

    if request.method == 'POST':
      usuario = request.form.get('usuario', '').strip()
      password = request.form.get('password', '')
      ejecutar(
          cursor,
          '''
          SELECT u.*, e.nombre AS empresa_nombre
          FROM usuarios u JOIN empresas e ON e.id = u.empresa_id
          WHERE u.usuario = ?
          ''',
          (usuario,),
      )
      registro = cursor.fetchone()
      if registro and check_password_hash(registro['password_hash'], password):
        iniciar_sesion(registro)
        destino = request.args.get('siguiente', '')
        if not destino.startswith('/') or destino.startswith('//'):
          destino = url_for('index')
        return redirect(destino)
      flash('Usuario o contraseña incorrectos.', 'error')
  return render_template('login.html')


@app.post('/salir')
@requiere_login
def salir():
  session.clear()
  flash('Saliste de tu cuenta.', 'success')
  return redirect(url_for('login'))


@app.route('/')
@requiere_login
def index():
  with obtener_conexion() as conexion:
    cursor = conexion.cursor()
    ejecutar(
        cursor,
        '''
        SELECT COUNT(*) AS total FROM productos
        WHERE activo = TRUE AND empresa_id = ?
        ''',
        (session['empresa_id'],),
    )
    total_productos = cursor.fetchone()['total']
    ejecutar(
        cursor,
        '''
        SELECT COALESCE(SUM(e.cantidad * p.precio), 0) AS valor
        FROM existencias e
        JOIN productos p
          ON p.id = e.producto_id AND p.empresa_id = e.empresa_id
        WHERE p.activo = TRUE AND p.empresa_id = ?
        ''',
        (session['empresa_id'],),
    )
    valor_total = cursor.fetchone()['valor']
    ejecutar(
        cursor,
        '''
        SELECT COUNT(*) AS total FROM existencias e
        JOIN productos p
          ON p.id = e.producto_id AND p.empresa_id = e.empresa_id
        JOIN ubicaciones u
          ON u.id = e.ubicacion_id AND u.empresa_id = e.empresa_id
        WHERE p.activo = TRUE AND u.activa = TRUE
          AND e.cantidad <= p.stock_minimo AND p.empresa_id = ?
        ''',
        (session['empresa_id'],),
    )
    stock_critico = cursor.fetchone()['total']
    ejecutar(
        cursor,
        '''
        SELECT p.nombre AS producto, u.nombre AS ubicacion,
          COALESCE(e.cantidad, 0) AS cantidad, p.stock_minimo
        FROM existencias e
        JOIN productos p
          ON p.id = e.producto_id AND p.empresa_id = e.empresa_id
        JOIN ubicaciones u
          ON u.id = e.ubicacion_id AND u.empresa_id = e.empresa_id
        WHERE p.activo = TRUE AND u.activa = TRUE
          AND e.cantidad <= p.stock_minimo
          AND p.empresa_id = ? AND u.empresa_id = ?
        ORDER BY e.cantidad, p.nombre LIMIT 12
        ''',
        (session['empresa_id'], session['empresa_id']),
    )
    productos_bajos = cursor.fetchall()
    ejecutar(
        cursor,
        '''
        SELECT m.tipo, m.cantidad, m.creado_en, p.nombre AS producto,
          u.nombre AS ubicacion, a.nombre AS usuario
        FROM movimientos m
        JOIN productos p
          ON p.id = m.producto_id AND p.empresa_id = m.empresa_id
        JOIN ubicaciones u
          ON u.id = m.ubicacion_id AND u.empresa_id = m.empresa_id
        JOIN usuarios a
          ON a.id = m.usuario_id AND a.empresa_id = m.empresa_id
        WHERE m.empresa_id = ?
        ORDER BY m.id DESC LIMIT 8
        ''',
        (session['empresa_id'],),
    )
    ultimos_movimientos = cursor.fetchall()
  return render_template(
      'index.html',
      total_productos=total_productos,
      valor_total=valor_total,
      stock_critico=stock_critico,
      productos_bajos=productos_bajos,
      movimientos=ultimos_movimientos,
  )


@app.route('/productos')
@requiere_login
def productos():
  busqueda = request.args.get('busqueda', '').strip()
  try:
    ubicacion_id = int(request.args.get('ubicacion_id', '0'))
  except ValueError:
    ubicacion_id = 0

  with obtener_conexion() as conexion:
    cursor = conexion.cursor()
    ubicaciones = obtener_ubicaciones(cursor)
    if ubicaciones and not any(
        ubicacion['id'] == ubicacion_id for ubicacion in ubicaciones
    ):
      ubicacion_id = ubicaciones[0]['id']
    ejecutar(
        cursor,
        '''
        SELECT p.id, p.nombre, p.categoria, p.precio, p.codigo_barras,
          p.stock_minimo, COALESCE(e.cantidad, 0) AS stock
        FROM productos p
        LEFT JOIN existencias e
          ON e.producto_id = p.id AND e.ubicacion_id = ?
            AND e.empresa_id = p.empresa_id AND e.empresa_id = ?
        WHERE p.activo = TRUE AND p.empresa_id = ?
          AND (? = '' OR LOWER(p.nombre) LIKE LOWER(?)
            OR LOWER(p.categoria) LIKE LOWER(?)
            OR LOWER(COALESCE(p.codigo_barras, '')) LIKE LOWER(?))
        ORDER BY p.nombre
        ''',
        (
            ubicacion_id,
            session['empresa_id'],
            session['empresa_id'],
            busqueda,
            f'%{busqueda}%',
            f'%{busqueda}%',
            f'%{busqueda}%',
        ),
    )
    lista_productos = cursor.fetchall()
  return render_template(
      'productos.html',
      productos=lista_productos,
      busqueda=busqueda,
      ubicaciones=ubicaciones,
      ubicacion_id=ubicacion_id,
  )


@app.route('/productos/nuevo', methods=['GET', 'POST'])
@requiere_login
def nuevo_producto():
  with obtener_conexion() as conexion:
    cursor = conexion.cursor()
    ubicaciones = obtener_ubicaciones(cursor)
    if request.method == 'POST':
      nombre = request.form.get('nombre', '').strip()
      descripcion = request.form.get('descripcion', '').strip()
      categoria = request.form.get('categoria', '').strip()
      codigo_barras = request.form.get('codigo_barras', '').strip() or None
      try:
        precio = validar_precio(request.form.get('precio', ''))
        precio_db = precio if es_postgres() else float(precio)
        cantidad = validar_entero_no_negativo(
            request.form.get('stock', '0'), 'El stock inicial'
        )
        stock_minimo = validar_entero_no_negativo(
            request.form.get('stock_minimo', '5'), 'El stock mínimo'
        )
        ubicacion_id = int(request.form.get('ubicacion_id', ''))
        if (
            not nombre or len(nombre) > 150
            or not categoria or len(categoria) > 100
            or (codigo_barras and len(codigo_barras) > 80)
            or len(descripcion) > 1000
        ):
          raise ValueError('El nombre y la categoría son obligatorios.')
        if not any(loc['id'] == ubicacion_id for loc in ubicaciones):
          raise ValueError('Selecciona una ubicación válida.')

        ejecutar(
            cursor,
            '''
            INSERT INTO productos
              (nombre, descripcion, precio, stock, categoria, codigo_barras,
               stock_minimo, empresa_id)
            VALUES (?, ?, ?, 0, ?, ?, ?, ?)
            ''' + (' RETURNING id' if es_postgres() else ''),
            (
                nombre,
                descripcion,
                precio_db,
                categoria,
                codigo_barras,
                stock_minimo,
                session['empresa_id'],
            ),
        )
        producto_id = (
            cursor.fetchone()['id'] if es_postgres() else cursor.lastrowid
        )
        ejecutar(
            cursor,
            '''
            INSERT INTO existencias
              (producto_id, ubicacion_id, cantidad, empresa_id)
            VALUES (?, ?, 0, ?)
            ON CONFLICT (producto_id, ubicacion_id) DO NOTHING
            ''',
            (producto_id, ubicacion_id, session['empresa_id']),
        )
        if cantidad:
          registrar_movimiento(
              cursor,
              producto_id,
              ubicacion_id,
              session['usuario_id'],
              'inicial',
              cantidad,
              session['empresa_id'],
              nota='Stock inicial',
          )
        flash('Producto creado. Ya puedes registrar compras y ventas.', 'success')
        return redirect(url_for('productos', ubicacion_id=ubicacion_id))
      except (ValueError, InvalidOperation) as error:
        flash(str(error), 'error')
      except ERRORES_INTEGRIDAD:
        conexion.rollback()
        flash('Ese código de barras ya está registrado.', 'error')
  return render_template(
      'nuevo_producto.html',
      ubicaciones=ubicaciones,
      ubicacion_id=ubicaciones[0]['id'] if ubicaciones else None,
  )


@app.route('/productos/editar/<int:id>', methods=['GET', 'POST'])
@requiere_login
def editar_producto(id):
  with obtener_conexion() as conexion:
    cursor = conexion.cursor()
    ejecutar(
        cursor,
        '''
        SELECT * FROM productos
        WHERE id = ? AND empresa_id = ? AND activo = TRUE
        ''',
        (id, session['empresa_id']),
    )
    producto = cursor.fetchone()
    if not producto:
      flash('El producto no existe o fue archivado.', 'error')
      return redirect(url_for('productos'))

    if request.method == 'POST':
      try:
        nombre = request.form.get('nombre', '').strip()
        categoria = request.form.get('categoria', '').strip()
        precio = validar_precio(request.form.get('precio', ''))
        precio_db = precio if es_postgres() else float(precio)
        stock_minimo = validar_entero_no_negativo(
            request.form.get('stock_minimo', '5'), 'El stock mínimo'
        )
        codigo_barras = request.form.get('codigo_barras', '').strip() or None
        descripcion = request.form.get('descripcion', '').strip()
        if (
            not nombre or len(nombre) > 150
            or not categoria or len(categoria) > 100
            or (codigo_barras and len(codigo_barras) > 80)
            or len(descripcion) > 1000
        ):
          raise ValueError('Revisa el nombre, la categoría y el stock mínimo.')
        ejecutar(
            cursor,
            '''
            UPDATE productos SET nombre = ?, descripcion = ?, precio = ?,
              categoria = ?, codigo_barras = ?, stock_minimo = ?
            WHERE id = ? AND empresa_id = ?
            ''',
            (
                nombre,
                descripcion,
                precio_db,
                categoria,
                codigo_barras,
                stock_minimo,
                id,
                session['empresa_id'],
            ),
        )
        flash('Producto actualizado.', 'success')
        return redirect(url_for('productos'))
      except (ValueError, InvalidOperation) as error:
        flash(str(error), 'error')
      except ERRORES_INTEGRIDAD:
        conexion.rollback()
        flash('Ese código de barras ya está registrado.', 'error')
    ubicaciones = obtener_ubicaciones(cursor)
  return render_template(
      'editar_producto.html', producto=producto, ubicaciones=ubicaciones
  )


@app.post('/productos/ajustar/<int:id>/<string:accion>')
@requiere_login
def ajustar_stock(id, accion):
  if accion not in ('sumar', 'restar'):
    abort(404)
  try:
    try:
      ubicacion_id = int(request.form.get('ubicacion_id', ''))
    except (TypeError, ValueError):
      raise ValueError('Selecciona una ubicación válida.')
    with obtener_conexion() as conexion:
      cursor = conexion.cursor()
      ejecutar(
          cursor,
          'SELECT id FROM productos WHERE id = ? AND empresa_id = ? AND activo = TRUE',
          (id, session['empresa_id']),
      )
      if not cursor.fetchone():
        abort(404)
      ejecutar(
          cursor,
          'SELECT id FROM ubicaciones WHERE id = ? AND empresa_id = ? AND activa = TRUE',
          (ubicacion_id, session['empresa_id']),
      )
      if not cursor.fetchone():
        raise ValueError('Selecciona una ubicación activa.')
      registrar_movimiento(
          cursor,
          id,
          ubicacion_id,
          session['usuario_id'],
          'ajuste_entrada' if accion == 'sumar' else 'ajuste_salida',
          1,
          session['empresa_id'],
          nota='Ajuste rápido',
      )
    flash('Stock actualizado y movimiento registrado.', 'success')
  except ValueError as error:
    flash(str(error), 'error')
  return redirect(url_for('productos'))


@app.post('/productos/eliminar/<int:id>')
@requiere_admin
def eliminar_producto(id):
  with obtener_conexion() as conexion:
    cursor = conexion.cursor()
    ejecutar(
        cursor,
        '''
        SELECT COALESCE(SUM(cantidad), 0) AS stock
        FROM existencias WHERE producto_id = ? AND empresa_id = ?
        ''',
        (id, session['empresa_id']),
    )
    if cursor.fetchone()['stock'] > 0:
      flash(
          'No se puede archivar un producto con stock. Registra una venta o un ajuste de salida primero.',
          'error',
      )
    else:
      ejecutar(
          cursor,
          'UPDATE productos SET activo = FALSE '
          'WHERE id = ? AND empresa_id = ? AND activo = TRUE',
          (id, session['empresa_id']),
      )
      if cursor.rowcount:
        flash('Producto archivado; su historial se conserva.', 'success')
      else:
        flash('El producto no existe o ya fue archivado.', 'error')
  return redirect(url_for('productos'))


@app.route('/movimientos', methods=['GET', 'POST'])
@requiere_login
def movimientos():
  with obtener_conexion() as conexion:
    cursor = conexion.cursor()
    if request.method == 'POST':
      try:
        producto_id = int(request.form.get('producto_id', ''))
        ubicacion_id = int(request.form.get('ubicacion_id', ''))
        tipo = request.form.get('tipo', '')
        cantidad = validar_cantidad(request.form.get('cantidad', ''))
        if tipo not in ('compra', 'venta', 'ajuste_entrada', 'ajuste_salida'):
          raise ValueError('Selecciona un tipo de movimiento válido.')
        ejecutar(
            cursor,
            'SELECT id FROM productos '
            'WHERE id = ? AND empresa_id = ? AND activo = TRUE',
            (producto_id, session['empresa_id']),
        )
        if not cursor.fetchone():
          raise ValueError('Selecciona un producto activo.')
        ejecutar(
            cursor,
            'SELECT id FROM ubicaciones '
            'WHERE id = ? AND empresa_id = ? AND activa = TRUE',
            (ubicacion_id, session['empresa_id']),
        )
        if not cursor.fetchone():
          raise ValueError('Selecciona una ubicación activa.')
        registrar_movimiento(
            cursor,
            producto_id,
            ubicacion_id,
            session['usuario_id'],
            tipo,
            cantidad,
            session['empresa_id'],
            request.form.get('proveedor', ''),
            request.form.get('nota', ''),
        )
        flash('Movimiento guardado en el historial.', 'success')
        return redirect(url_for('movimientos'))
      except (ValueError, InvalidOperation) as error:
        flash(str(error), 'error')

    ejecutar(
        cursor,
        'SELECT id, nombre FROM productos '
        'WHERE activo = TRUE AND empresa_id = ? ORDER BY nombre',
        (session['empresa_id'],),
    )
    productos_activos = cursor.fetchall()
    ubicaciones = obtener_ubicaciones(cursor)
    ejecutar(
        cursor,
        '''
        SELECT m.id, m.tipo, m.cantidad, m.proveedor, m.nota, m.creado_en,
          p.nombre AS producto, u.nombre AS ubicacion, a.nombre AS usuario
        FROM movimientos m
        JOIN productos p
          ON p.id = m.producto_id AND p.empresa_id = m.empresa_id
        JOIN ubicaciones u
          ON u.id = m.ubicacion_id AND u.empresa_id = m.empresa_id
        JOIN usuarios a
          ON a.id = m.usuario_id AND a.empresa_id = m.empresa_id
        WHERE m.empresa_id = ?
        ORDER BY m.id DESC LIMIT 200
        ''',
        (session['empresa_id'],),
    )
    historial = cursor.fetchall()
  return render_template(
      'movimientos.html',
      productos=productos_activos,
      ubicaciones=ubicaciones,
      historial=historial,
  )


@app.get('/reportes/movimientos.csv')
@requiere_login
def exportar_movimientos():
  with obtener_conexion() as conexion:
    cursor = conexion.cursor()
    ejecutar(
        cursor,
        '''
        SELECT m.creado_en, p.nombre AS producto, u.nombre AS ubicacion,
          a.nombre AS usuario, m.tipo, m.cantidad, m.proveedor, m.nota
        FROM movimientos m
        JOIN productos p
          ON p.id = m.producto_id AND p.empresa_id = m.empresa_id
        JOIN ubicaciones u
          ON u.id = m.ubicacion_id AND u.empresa_id = m.empresa_id
        JOIN usuarios a
          ON a.id = m.usuario_id AND a.empresa_id = m.empresa_id
        WHERE m.empresa_id = ?
        ORDER BY m.id DESC
        ''',
        (session['empresa_id'],),
    )
    filas = cursor.fetchall()
  lineas = ['Fecha,Producto,Ubicacion,Usuario,Tipo,Cantidad,Proveedor,Nota']
  for fila in filas:
    valores = [str(fila[campo] or '') for campo in (
        'creado_en', 'producto', 'ubicacion', 'usuario', 'tipo', 'cantidad',
        'proveedor', 'nota'
    )]
    valores = [
        "'" + valor
        if valor.lstrip(' \t\r\n').startswith(('=', '+', '-', '@'))
        else valor
        for valor in valores
    ]
    lineas.append(
        ','.join('"' + valor.replace('"', '""') + '"' for valor in valores)
    )
  contenido = '\ufeff' + '\r\n'.join(lineas)
  return Response(
      contenido,
      mimetype='text/csv',
      headers={'Content-Disposition': 'attachment; filename=movimientos.csv'},
  )


@app.route('/ubicaciones', methods=['GET', 'POST'])
@requiere_admin
def ubicaciones():
  with obtener_conexion() as conexion:
    cursor = conexion.cursor()
    if request.method == 'POST':
      nombre = request.form.get('nombre', '').strip()
      if not nombre or len(nombre) > 120:
        flash('Escribe un nombre de hasta 120 caracteres.', 'error')
      else:
        try:
          ejecutar(
              cursor,
              'INSERT INTO ubicaciones (nombre, empresa_id) VALUES (?, ?)',
              (nombre, session['empresa_id']),
          )
          flash('Ubicación creada.', 'success')
        except ERRORES_INTEGRIDAD:
          conexion.rollback()
          flash('Ya existe una ubicación con ese nombre.', 'error')
    ubicaciones_todas = obtener_ubicaciones(cursor, solo_activas=False)
  return render_template('ubicaciones.html', ubicaciones=ubicaciones_todas)


@app.route('/usuarios', methods=['GET', 'POST'])
@requiere_admin
def usuarios():
  with obtener_conexion() as conexion:
    cursor = conexion.cursor()
    if request.method == 'POST':
      nombre = request.form.get('nombre', '').strip()
      usuario = request.form.get('usuario', '').strip()
      password = request.form.get('password', '')
      rol = request.form.get('rol', '')
      if (
          not nombre or len(nombre) > 120
          or len(usuario) < 3 or len(usuario) > 80
          or len(password) < 12
      ):
        flash(
            'Completa el nombre, usa un usuario de 3 caracteres y una '
            'contraseña de al menos 12 caracteres.',
            'error',
        )
      elif rol not in ('admin', 'operador'):
        flash('Selecciona un rol válido.', 'error')
      else:
        try:
          ejecutar(
              cursor,
              '''
              INSERT INTO usuarios
                (nombre, usuario, password_hash, rol, empresa_id)
              VALUES (?, ?, ?, ?, ?)
              ''',
              (
                  nombre,
                  usuario,
                  generate_password_hash(password),
                  rol,
                  session['empresa_id'],
              ),
          )
          flash('Usuario creado.', 'success')
        except ERRORES_INTEGRIDAD:
          conexion.rollback()
          flash('Ese nombre de usuario ya está en uso.', 'error')
    ejecutar(
        cursor,
        'SELECT id, nombre, usuario, rol, creado_en FROM usuarios '
        'WHERE empresa_id = ? ORDER BY nombre',
        (session['empresa_id'],),
    )
    lista_usuarios = cursor.fetchall()
  return render_template('usuarios.html', usuarios=lista_usuarios)


if __name__ == '__main__':
  app.run(
      host=os.environ.get('HOST', '127.0.0.1'),
      port=int(os.environ.get('PORT', '5000')),
      debug=os.environ.get('FLASK_DEBUG') == '1',
  )
