from flask import Flask, render_template, request, redirect, url_for, flash
import sqlite3

app = Flask(__name__)
app.secret_key = 'clave_secreta_stock'

def obtener_conexion():
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
    valor_total = cursor.fetchone()[0] or 0
    
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
        productos=ultimos_productos
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
            WHERE nombre LIKE ? OR categoria LIKE ? 
            ORDER BY nombre ASC
        '''
        cursor.execute(query, (f'%{busqueda}%', f'%{busqueda}%'))
    else:
        cursor.execute('SELECT * FROM productos ORDER BY nombre ASC')
        
    lista_productos = cursor.fetchall()
    conexion.close()
    
    return render_template('productos.html', productos=lista_productos, busqueda=busqueda)

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
        cursor.execute('''
            INSERT INTO productos (nombre, descripcion, precio, stock, categoria)
            VALUES (?, ?, ?, ?, ?)
        ''', (nombre, descripcion, precio, stock, categoria))
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
        
        cursor.execute('''
            UPDATE productos 
            SET nombre = ?, descripcion = ?, precio = ?, stock = ?, categoria = ?
            WHERE id = ?
        ''', (nombre, descripcion, precio, stock, categoria, id))
        conexion.commit()
        conexion.close()
        
        flash('¡Producto actualizado con éxito!')
        return redirect(url_for('productos'))
        
    cursor.execute('SELECT * FROM productos WHERE id = ?', (id,))
    producto = cursor.fetchone()
    conexion.close()
    
    return render_template('editar_producto.html', producto=producto)


# Ajustar stock rápido (+ / -)
@app.route('/productos/ajustar/<int:id>/<string:accion>', methods=['POST'])
def ajustar_stock(id, accion):
    conexion = obtener_conexion()
    cursor = conexion.cursor()
    
    if accion == 'sumar':
        cursor.execute('UPDATE productos SET stock = stock + 1 WHERE id = ?', (id,))
    elif accion == 'restar':
        cursor.execute('UPDATE productos SET stock = MAX(0, stock - 1) WHERE id = ?', (id,))
        
    conexion.commit()
    conexion.close()
    
    return redirect(url_for('productos'))

# Eliminar producto
@app.route('/productos/eliminar/<int:id>', methods=['POST'])
def eliminar_producto(id):
    conexion = obtener_conexion()
    cursor = conexion.cursor()
    cursor.execute('DELETE FROM productos WHERE id = ?', (id,))
    conexion.commit()
    conexion.close()
    
    flash('¡Producto eliminado con éxito!')
    return redirect(url_for('productos'))

if __name__ == '__main__':
    app.run(debug=True)