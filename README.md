# Registro EPF — App para el equipo

App en Streamlit para procesar los chats de WhatsApp exportados, extraer los
datos del Registro de Enfermedades Poco Frecuentes y llevar el seguimiento
del equipo.

## Cómo desplegarla (Streamlit Community Cloud — gratis)

1. Creá un repositorio en GitHub (puede ser privado) y subí estos archivos:
   `app.py`, `extraction.py`, `whatsapp_parser.py`, `requirements.txt`.
   **No subas** `.streamlit/secrets.toml` (solo el `.example`).
2. Entrá a https://share.streamlit.io con tu cuenta de GitHub.
3. "New app" → elegí el repo → archivo principal `app.py` → Deploy.
4. Andá a **Settings → Secrets** de la app y pegá el contenido de
   `.streamlit/secrets.toml.example` con tus valores reales:
   ```
   PROVIDER = "anthropic"          # o "gemini"
   ANTHROPIC_API_KEY = "tu-api-key-real"    # si usás PROVIDER = "anthropic"
   GEMINI_API_KEY = "tu-api-key-real"       # si usás PROVIDER = "gemini"
   APP_PASSWORD = "la-contraseña-que-le-vas-a-dar-al-equipo"
   ```
   Solo hace falta cargar la key del proveedor que elijas — no ambas.
   Podés cambiar de proveedor en cualquier momento editando `PROVIDER` en
   Secrets y reiniciando la app, sin tocar código.
5. Listo — la URL que te da Streamlit Cloud es la que compartís con tus
   compañeros. Les pedís la contraseña para entrar.

## Cómo probarla en tu compu antes de subirla

```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# editá .streamlit/secrets.toml con tu API key real y una contraseña
streamlit run app.py
```

## Importante — persistencia de datos

Streamlit Community Cloud **no garantiza que los datos cargados en la sesión
sobrevivan** a un reinicio de la app (se reinicia solo, por inactividad o
al actualizar el código). Por eso la app tiene:

- Un botón para **descargar la base en Excel** — hacelo seguido, es tu
  respaldo real.
- Un botón para **restaurar la base desde un Excel** — así si la app se
  reinicia, subís el último Excel guardado y seguís donde quedaste.

Si el uso crece y esto se vuelve incómodo, el siguiente paso natural es
sumar una base de datos externa persistente (por ejemplo Supabase, que
tiene un plan gratuito) en vez de depender de la sesión + Excel.

## Seguridad

- La contraseña (`APP_PASSWORD`) es compartida para todo el equipo por
  simplicidad. Si en algún momento necesitan saber quién cargó o editó
  cada registro, hay que pasar a login individual — avisen y lo armamos.
- Los datos que maneja esta app son datos de salud identificables (DNI,
  diagnóstico, domicilio). No compartan la URL ni la contraseña fuera del
  equipo del instituto.
