from flask import Flask, render_template, request, redirect, url_for, flash
import os
import sqlite3

# Intentamos importar psycopg2 o manejar la conexión según corresponda
# Flask-SQLAlchemy o manejo nativo con adaptadores estándar
try:
  import psycopg2
  import psycopg2.extras
except ImportError:
  pass

app = Flask(__name__)
app.secret_key = 'clave_secreta_stock'

# ==========================================
# CONFIGURACIÓN INTELIGENTE DE BASE DE DATOS
# (PostgreSQL en Render / SQLite local)
# ==========================================
database_url = os.environ.get('DATABASE_URL')

if database_url:
  if database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)


def obtener_conexion():
  if database_url:
    # Conexión profesional a PostgreSQL en la nube de Render
    conexion = psycopg2.connect(database_url, cursor_factory=psycopg2.extras.RealDictCursor)
    return conexion
  else:
    # Conexión local a SQLite para desarrollo en tu Lenovo
    conexion = sqlite3.connect('stock.db')
    conexion.row_factory = sqlite3.Row  # Permite acceder a las columnas por nombre
    return conexion


# Dashboard Principal
@app.route('/')
def index():
  conexion = obtener_conexion()
  cursor = conexion.cursor()

  # Métricas del inventario
  cursor.execute('SELECT COUNT(*) FROM productos')
  total_productos = cursor.fetchone()[0]

  cursor.execute('SELECT SUM(precio * stock) FROM productos')
  resultado_valor = cursor.fetchone()[0]
  valor_total = resultado_valor if resultado_valor is not None else 0

  # Productos con stock bajo (menor o igual a 5 unidades)
  cursor.execute('SELECT COUNT(*) FROM productos WHERE stock <= 5')
  stock_critico = cursor.fetchone()[0]

  # Obtener últimos productos agregados
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


# Listado completo de inventario con Búsqueda
@app.route('/productos')
def productos():
  busqueda = request.args.get('busqueda', '')
  conexion = obtener_conexion()
  cursor = conexion.cursor()

  if busqueda:
    query = '''
            SELECT * FROM productos 
            WHERE nombre LIKE %s OR categoria %s 
            ORDER BY nombre ASC
        ''' if database_url else '''
            SELECT * FROM productos 
            WHERE nombre LIKE ? OR categoria LIKE ? 
            ORDER BY nombre ASC
        '''
    cursor.execute(query, (f'%{busqueda}%', f'%{busqueda}%'))
  else:
    cursor.execute('SELECT * FROM productos ORDER BY nombre ASC')

  lista_productos = cursor.fetchall()
  conexion.close()

  return render_template(
      'productos.html', productos=lista_productos, busqueda=busqueda
  )


# Alta de nuevo producto
@app.route('/productos/nuevo', methods=['GET', 'POST'])
def nuevo_producto():
  if request.method == 'POST':
    nombre = request.form['nombre']
    descripcion = request.form['descripcion']
    precio = float(request.form['precio'])
    stock = int(request.form['stock'])
    categoria = request.form['categoria']

    conexion = obtener_conexion()
    cursor = conexion.cursor()

    query = '''
            INSERT INTO productos (nombre, descripcion, precio, stock, categoria)
            VALUES (%s, %s, %s, %s, %s)
        ''' if database_url else '''
            INSERT INTO productos (nombre, descripcion, precio, stock, categoria)
            VALUES (?, ?, ?, ?, ?)
        '''
    cursor.execute(query, (nombre, descripcion, precio, stock, categoria))
    conexion.commit()
    conexion.close()

    flash('¡Producto registrado con éxito!')
    return redirect(url_for('productos'))

  return render_template('nuevo_producto.html')


@app.route('/productos/editar/<int:id>', methods=['GET', 'POST'])
def editar_producto(id):
  conexion = obtener_conexion()
  cursor = conexion.cursor()

  if request.method == 'POST':
    nombre = request.form['nombre']
    descripcion = request.form['descripcion']
    precio = float(request.form['precio'])
    stock = int(request.form['stock'])
    categoria = request.form['categoria']

    query = '''
            UPDATE productos 
            SET nombre = %s, descripcion = %s, precio = %s, stock = %s, categoria = %s
            WHERE id = %s
        ''' if database_url else '''
            UPDATE productos 
            SET nombre = ?, descripcion = ?, precio = ?, stock = ?, categoria = ?
            WHERE id = ?
        '''
    cursor.execute(
        query, (nombre, descripcion, precio, stock, categoria, id)
    )
    conexion.commit()
    conexion.close()

    flash('¡Producto actualizado con éxito!')
    return redirect(url_for('productos'))

  query_select = (
      'SELECT * FROM productos WHERE id = %s'
      if database_url
      else 'SELECT * FROM productos WHERE id = ?'
  )
  cursor.execute(query_select, (id,))
  producto = cursor.fetchone()
  conexion.close()

  return render_template('editar_producto.html', producto=producto)


# Ajustar stock rápido (+ / -)
@app.route('/productos/ajustar/<int:id>/<string:accion>', methods=['POST'])
def ajustar_stock(id, accion):
  conexion = obtener_conexion()
  cursor = conexion.cursor()

  if accion == 'sumar':
    query = (
        'UPDATE productos SET stock = stock + 1 WHERE id = %s'
        if database_url
        else 'UPDATE productos SET stock = stock + 1 WHERE id = ?'
    )
    cursor.execute(query, (id,))
  elif accion == 'restar':
    query = (
        'UPDATE productos SET stock = GREATEST(0, stock - 1) WHERE id = %s'
        if database_url
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
      if database_url
      else 'DELETE FROM productos WHERE id = ?'
  )
  cursor.execute(query, (id,))
  conexion.commit()
  conexion.close()

  flash('¡Producto eliminado con éxito!')
  return redirect(url_for('productos'))


if __name__ == '__main__':
  app.run(debug=True)