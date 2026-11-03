import os
import sqlite3
import traceback
from flask import Flask, flash, redirect, render_template, request, url_for

try:
  import psycopg2
  import psycopg2.extras

  POSTGRES_DISPONIBLE = True
except ImportError:
  POSTGRES_DISPONIBLE = False

app = Flask(__name__)
app.secret_key = 'clave_secreta_stock'

# Configuración de base de datos
database_url = os.environ.get('DATABASE_URL')

if database_url:
  if database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)


def obtener_conexion():
  if database_url and POSTGRES_DISPONIBLE:
    conexion = psycopg2.connect(
        database_url, cursor_factory=psycopg2.extras.DictCursor
    )
    return conexion
  else:
    conexion = sqlite3.connect('stock.db')
    conexion.row_factory = sqlite3.Row
    return conexion


# Función automática para asegurar que la tabla productos exista siempre
def inicializar_base_datos():
  try:
    conexion = obtener_conexion()
    cursor = conexion.cursor()

    if database_url and POSTGRES_DISPONIBLE:
      cursor.execute('''
                CREATE TABLE IF NOT EXISTS productos (
                    id SERIAL PRIMARY KEY,
                    nombre VARCHAR(150) NOT NULL,
                    descripcion TEXT,
                    precio NUMERIC(10, 2) NOT NULL,
                    stock INT NOT NULL,
                    categoria VARCHAR(100) NOT NULL
                )
            ''')
    else:
      cursor.execute('''
                CREATE TABLE IF NOT EXISTS productos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nombre TEXT NOT NULL,
                    descripcion TEXT,
                    precio REAL NOT NULL,
                    stock INTEGER NOT NULL,
                    categoria TEXT NOT NULL
                )
            ''')

    conexion.commit()
    conexion.close()
  except Exception as e:
    print(f'Error al inicializar la base de datos: {e}')


# Ejecutamos la inicialización al arrancar la app
inicializar_base_datos()


# Dashboard Principal
@app.route('/')
def index():
  try:
    conexion = obtener_conexion()
    cursor = conexion.cursor()

    cursor.execute('SELECT COUNT(*) FROM productos')
    total_productos = cursor.fetchone()[0]

    cursor.execute('SELECT SUM(precio * stock) FROM productos')
    resultado_valor = cursor.fetchone()[0]
    valor_total = resultado_valor if resultado_valor is not None else 0

    cursor.execute('SELECT COUNT(*) FROM productos WHERE stock <= 5')
    stock_critico = cursor.fetchone()[0]

    cursor.execute('SELECT * FROM productos ORDER BY id DESC LIMIT 5')
    ultimos_productos = cursor.fetchall()

    conexion.close()

    return render_template(
        'index.html',
        total_productos=total_productos,
        valor_total=valor_total,
        stock_critico=stock_critico,
        productos=ultimos_productos,
    )
  except Exception as e:
    print('ERROR EN INDEX:')
    traceback.print_exc()
    raise


# Listado completo de inventario con Búsqueda
@app.route('/productos')
def productos():
  try:
    busqueda = request.args.get('busqueda', '')
    conexion = obtener_conexion()
    cursor = conexion.cursor()

    if busqueda:
      query = (
          '''
                SELECT * FROM productos 
                WHERE nombre ILIKE %s OR categoria ILIKE %s 
                ORDER BY nombre ASC
            '''
          if database_url and POSTGRES_DISPONIBLE
          else '''
                SELECT * FROM productos 
                WHERE nombre LIKE ? OR categoria LIKE ? 
                ORDER BY nombre ASC
            '''
      )
      cursor.execute(query, (f'%{busqueda}%', f'%{busqueda}%'))
    else:
      cursor.execute('SELECT * FROM productos ORDER BY nombre ASC')

    lista_productos = cursor.fetchall()
    conexion.close()

    return render_template(
        'productos.html', productos=lista_productos, busqueda=busqueda
    )
  except Exception as e:
    print('ERROR EN PRODUCTOS:')
    traceback.print_exc()
    raise


# Alta de nuevo producto con manejo seguro y traza de error explícita
@app.route('/productos/nuevo', methods=['GET', 'POST'])
def nuevo_producto():
  if request.method == 'POST':
    try:
      nombre = request.form.get('nombre', '').strip()
      descripcion = request.form.get('descripcion', '').strip()
      try:
        precio = float(request.form.get('precio', 0))
      except ValueError:
        precio = 0.0
      try:
        stock = int(request.form.get('stock', 0))
      except ValueError:
        stock = 0
      categoria = request.form.get('categoria', '').strip()

      conexion = obtener_conexion()
      cursor = conexion.cursor()

      query = (
          '''
                INSERT INTO productos (nombre, descripcion, precio, stock, categoria)
                VALUES (%s, %s, %s, %s, %s)
            '''
          if database_url and POSTGRES_DISPONIBLE
          else '''
                INSERT INTO productos (nombre, descripcion, precio, stock, categoria)
                VALUES (?, ?, ?, ?, ?)
            '''
      )
      cursor.execute(query, (nombre, descripcion, precio, stock, categoria))
      conexion.commit()
      conexion.close()

      flash('¡Producto registrado con éxito!')
      return redirect(url_for('productos'))
    except Exception as e:
      print('*** ERROR CRITICO EN NUEVO_PRODUCTO (POST) ***')
      traceback.print_exc()
      raise

  return render_template('nuevo_producto.html')


@app.route('/productos/editar/<int:id>', methods=['GET', 'POST'])
def editar_producto(id):
  conexion = obtener_conexion()
  cursor = conexion.cursor()

  if request.method == 'POST':
    try:
      nombre = request.form.get('nombre', '').strip()
      descripcion = request.form.get('descripcion', '').strip()
      try:
        precio = float(request.form.get('precio', 0))
      except ValueError:
        precio = 0.0
      try:
        stock = int(request.form.get('stock', 0))
      except ValueError:
        stock = 0
      categoria = request.form.get('categoria', '').strip()

      query = (
          '''
                UPDATE productos 
                SET nombre = %s, descripcion = %s, precio = %s, stock = %s, categoria = %s
                WHERE id = %s
            '''
          if database_url and POSTGRES_DISPONIBLE
          else '''
                UPDATE productos 
                SET nombre = ?, descripcion = ?, precio = ?, stock = ?, categoria = ?
                WHERE id = ?
            '''
      )
      cursor.execute(
          query, (nombre, descripcion, precio, stock, categoria, id)
      )
      conexion.commit()
      conexion.close()

      flash('¡Producto actualizado con éxito!')
      return redirect(url_for('productos'))
    except Exception as e:
      print('*** ERROR CRITICO EN EDITAR_PRODUCTO (POST) ***')
      traceback.print_exc()
      raise

  query_select = (
      'SELECT * FROM productos WHERE id = %s'
      if database_url and POSTGRES_DISPONIBLE
      else 'SELECT * FROM productos WHERE id = ?'
  )
  cursor.execute(query_select, (id,))
  producto = cursor.fetchone()
  conexion.close()

  if not producto:
    flash('El producto no existe.')
    return redirect(url_for('productos'))

  return render_template('editar_producto.html', producto=producto)


# Ajustar stock rápido (+ / -)
@app.route('/productos/ajustar/<int:id>/<string:accion>', methods=['POST'])
def ajustar_stock(id, accion):
  conexion = obtener_conexion()
  cursor = conexion.cursor()

  if accion == 'sumar':
    query = (
        'UPDATE productos SET stock = stock + 1 WHERE id = %s'
        if database_url and POSTGRES_DISPONIBLE
        else 'UPDATE productos SET stock = stock + 1 WHERE id = ?'
    )
    cursor.execute(query, (id,))
  elif accion == 'restar':
    query = (
        'UPDATE productos SET stock = GREATEST(0, stock - 1) WHERE id = %s'
        if database_url and POSTGRES_DISPONIBLE
        else (
            'UPDATE productos SET stock = MAX(0, stock - 1) WHERE id = ?'
        )
    )
    cursor.execute(query, (id,))

  conexion.commit()
  conexion.close()

  return redirect(url_for('productos'))


# Eliminar producto
@app.route('/productos/eliminar/<int:id>', methods=['POST'])
def eliminar_producto(id):
  conexion = obtener_conexion()
  cursor = conexion.cursor()
  query = (
      'DELETE FROM productos WHERE id = %s'
      if database_url and POSTGRES_DISPONIBLE
      else 'DELETE FROM productos WHERE id = ?'
  )
  cursor.execute(query, (id,))
  conexion.commit()
  conexion.close()

  flash('¡Producto eliminado con éxito!')
  return redirect(url_for('productos'))


if __name__ == '__main__':
  app.run(debug=True)