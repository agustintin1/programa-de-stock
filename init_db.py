import sqlite3

def inicializar_stock():
    conexion = sqlite3.connect('stock.db')
    cursor = conexion.cursor()

    # Creamos la tabla de productos
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS productos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            descripcion TEXT NOT NULL,
            precio REAL NOT NULL,
            stock INTEGER NOT NULL,
            categoria TEXT NOT NULL
        )
    ''')

    # Insertamos algunos productos iniciales si la tabla está vacía
    cursor.execute('SELECT COUNT(*) FROM productos')
    if cursor.fetchone()[0] == 0:
        productos_iniciales = [
            ("Whey Protein 1kg", "Suplemento de proteína de suero de leche sabor chocolate", 28500.0, 15, "Suplementos"),
            ("Shaker Deportivo", "Vaso mezclador anti-fugas con rejilla", 4500.0, 30, "Accesorios"),
            ("Creatina Monohidratada 300g", "Creatina pura micronizada de alta absorción", 22000.0, 4, "Suplementos"),
            ("Barra de Cereal Energética", "Barra de avena y frutos secos", 1200.0, 50, "Alimentos")
        ]
        cursor.executemany('''
            INSERT INTO productos (nombre, descripcion, precio, stock, categoria)
            VALUES (?, ?, ?, ?, ?)
        ''', productos_iniciales)
        print("¡Productos iniciales de stock cargados con éxito!")

    conexion.commit()
    conexion.close()
    print("¡Base de datos 'stock.db' inicializada correctamente!")

if __name__ == '__main__':
    inicializar_stock()