# UrbanReport

Plataforma comunitaria web para la gestión, seguimiento y resolución de reportes e incidencias ciudadanas con geolocalización, interacción social y panel de moderación administrativa.

---
## ¡UrbanReport ya esta desplegado en la web!

Si no deseas realizar la instalación del proyecto con todas sus dependencias puedes visitar nuestro sitio web ingresando al siguiente link:

* https://urbanreport.onrender.com
  
>[Nota!]
> Si eres nuestro tester y quieres probar un usuario de administrador y superadmin contáctanos a los siguientes correos:
>
> **Solo se va a responder al correo si se envía desde el dominio de UNIMINUTO (@uniminuto.edu.co).**
> * juan.sanchez-oc@uniminuto.edu.co
> * juan.cardona-sa@uniminuto.edu.co
> 
> Si te muestra una pantalla de carga que dice "Render" no te preocupes! Es nuestro aliado para desplegar la APP, tarda unos pocos segundos para mostrar la interfaz de UrbanReport.

## Requisitos Previos

Asegúrate de tener instalados los siguientes componentes en tu sistema:

* **Python 3.10+** (probado y compatible hasta Python 3.12+)
* **Git**
* Un navegador web moderno

---

## Instalación y Configuración

Sigue estos pasos para poner en marcha el proyecto en tu entorno local:

### 1. Clonar el repositorio
```bash
git clone https://github.com/TU_USUARIO/UrbanReport.git
cd UrbanReport
```

### 2. Crear y activar el entorno virtual

* **En Windows (PowerShell):**
  ```powershell
  python -m venv .venv
  .venv\Scripts\Activate.ps1
  ```
  *(Si PowerShell bloquea scripts, ejecuta antes: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned`)*

* **En Windows (CMD):**
  ```cmd
  python -m venv .venv
  .venv\Scripts\activate.bat
  ```

* **En Linux / macOS:**
  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  ```

### 3. Instalar dependencias
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configurar las variables de entorno (`.env`)
Copia la plantilla de configuración de ejemplo:

* **En Windows (PowerShell):**
  ```powershell
  Copy-Item .env.example .env
  ```
* **En Linux / macOS:**
  ```bash
  cp .env.example .env
  ```

> [NOTA!]
> Por defecto, si dejas vacías las variables de base de datos (`DB_NAME=`), el proyecto funcionará con una base de datos local **SQLite** (`db.sqlite3`) y almacenamiento de medios local sin requerir servicios en la nube. Si deseas conectar Supabase (PostgreSQL y S3 Media), rellena las credenciales indicadas en el archivo `.env`.

### 5. Aplicar migraciones
Prepara la base de datos ejecutando las migraciones de Django:
```bash
python manage.py migrate
```

---

## Ejecución del Servidor

Inicia el servidor local de desarrollo:

```bash
python manage.py runserver
```

Abre tu navegador e ingresa a:
 **[http://127.0.0.1:8000/](http://127.0.0.1:8000/)**

---

## Usuarios de Prueba

Para probar todas las funcionalidades del sistema (permisos, flujos de reporte, interacción comunitaria y moderación), dispones de los siguientes perfiles de prueba:

| Rol | Usuario | Correo Electrónico | Contraseña | Descripción / Permisos |
| :--- | :--- | :--- | :--- | :--- |
| **Administrador** | `admin` | `admin@urbanreport.com` | `AdminPassword123` | Control total, moderación de reportes (aprobar/declinar), censura de contenido y acceso al panel `/admin/`. |
| **Ciudadano 1** | `ciudadano` | `ciudadano@urbanreport.com` | `UserPassword123` | Creación de reportes en el mapa, subida de fotos, votación (like/dislike) y comentarios. |
| **Ciudadano 2** | `vecino` | `vecino@urbanreport.com` | `UserPassword123` | Usuario secundario para verificar seguimiento entre usuarios, notificaciones e hilos comunitarios. |

---

### Creación rápida de los usuarios de prueba

Si acabas de clonar el repositorio o estás iniciando con una base de datos limpia, puedes crear automáticamente los usuarios de prueba anteriores ejecutando este comando único en tu terminal:

* **En Windows / Linux / macOS (con el entorno virtual activo):**
```bash
python manage.py shell -c "from usuarios.models import Usuario; Usuario.objects.filter(username='admin').exists() or Usuario.objects.create_superuser('admin', 'admin@urbanreport.com', 'AdminPassword123', rol='ADMINISTRADOR', first_name='Admin', last_name='Principal'); Usuario.objects.filter(username='ciudadano').exists() or Usuario.objects.create_user('ciudadano', 'ciudadano@urbanreport.com', 'UserPassword123', rol='CIUDADANO', first_name='Carlos', last_name='Gómez', telefono='3001234567', direccion='Calle 10 # 40-20', barrio_vereda='Centro', codigo_postal='050001'); Usuario.objects.filter(username='vecino').exists() or Usuario.objects.create_user('vecino', 'vecino@urbanreport.com', 'UserPassword123', rol='CIUDADANO', first_name='María', last_name='López', telefono='3009876543', direccion='Carrera 45 # 12-30', barrio_vereda='Poblado', codigo_postal='050002'); print('Usuarios de prueba creados o verificados con éxito.')"
```

Alternativamente, puedes crear un superusuario interactivo con:
```bash
python manage.py createsuperuser
```

---

## Stack Tecnológico

* **Backend:** Python 3 & Django 6.x
* **Frontend:** Django Templates, HTML5, CSS3, JavaScript, Leaflet.js
* **Base de datos:** SQLite (desarrollo local por defecto) / PostgreSQL (Supabase)
* **Almacenamiento de archivos:** Almacenamiento local / Supabase Storage (S3 API con `django-storages`)
* **Autenticación:** Django Auth + `django-allauth` (soporte OAuth 2.0 Google/Facebook)
* **Archivos Estáticos:** WhiteNoise
