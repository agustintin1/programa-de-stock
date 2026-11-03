# Stock Claro

Aplicación web sencilla para llevar productos, depósitos, compras, ventas y el historial de cambios.

## Iniciar en Windows

Abre PowerShell en esta carpeta y ejecuta:

```powershell
.\.venv\Scripts\python.exe app.py
```

Si todavía no tienes el entorno virtual creado, instala las dependencias con:

```powershell
python -m pip install -r requirements.txt
python app.py
```

Abre <http://127.0.0.1:5000>. La primera vez, crea la cuenta administradora desde esa misma computadora. Después puedes crear cuentas de operador o administrador en **Equipo**.

Para ejecutar las pruebas automáticas:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

La aplicación conserva los productos de `stock.db` y los organiza inicialmente en **Depósito principal**. Los movimientos quedan asociados a la persona que los registra. Las ventas y los ajustes de salida no permiten dejar el stock negativo. El código de barras se puede escribir o escanear con un lector que funcione como teclado.

## Espacios para distintas empresas (beta)

Cada negocio puede crear su espacio desde **Crear cuenta** en `/registro`. Los productos, depósitos, usuarios, existencias e historial se separan por empresa. Los datos que ya existían se asignan al espacio inicial y no se comparten con los nuevos espacios.

Los nombres de usuario deben ser únicos en toda la aplicación, incluso entre empresas. El registro está abierto y todavía no verifica el correo ni limita altas automatizadas; úsalo solo para pruebas, no con información crítica ni como servicio comercial listo para producción. Antes de actualizar una instalación existente, haz y verifica una copia de seguridad de la base de datos, especialmente en PostgreSQL.

## Datos y configuración

- En modo local, la base de datos está en `stock.db`. Haz una copia de seguridad periódica; para copiarla con seguridad, detén la aplicación antes.
- Configura `SECRET_KEY` con un valor secreto y duradero antes de desplegar; de lo contrario, se genera uno nuevo al iniciar y las sesiones activas dejan de funcionar al reiniciar.
- `DATABASE_URL` permite usar PostgreSQL. Si se configura, la aplicación necesita `psycopg2-binary`.
- `STOCK_ADMIN_USERNAME` y `STOCK_ADMIN_PASSWORD` pueden crear el usuario administrador inicial en despliegues; la contraseña debe tener al menos 12 caracteres.
- Configura `COOKIE_SECURE=1` cuando el sitio use HTTPS.

## Importante

Esta es una primera versión para probar el flujo de inventario, no una plataforma empresarial lista para exponer en Internet. Antes de usarla con datos críticos o abrirla a una red pública, hacen falta pruebas y preparación operativa adicionales, como copias de seguridad verificadas, despliegue HTTPS, gestión segura de secretos, control de acceso por depósito y procedimientos de recuperación.
