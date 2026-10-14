#!/usr/bin/env bash
# Script de construcción para Render.
# Se ejecuta en cada deploy ANTES de arrancar el servidor.
set -o errexit  # aborta si algún comando falla

# 1. Instalar dependencias
pip install -r requirements.txt

# 2. Recopilar archivos estáticos (los sirve WhiteNoise)
python manage.py collectstatic --no-input

# 3. Aplicar migraciones pendientes a la base (Supabase)
python manage.py migrate
