# -*- coding: utf-8 -*-
"""
App de gestión del Registro EPF (Instituto de Genética Humana).

Permite subir chats de WhatsApp exportados (.txt o .zip), extraer los datos
del formulario de registro con IA, revisar/editar resultados, ver estadísticas
y exportar la base a Excel.
"""

import io
import zipfile
from pathlib import Path

import pandas as pd
import streamlit as st

from extraction import extract_from_conversation, get_provider
from whatsapp_parser import parse_whatsapp_txt, Conversation

st.set_page_config(page_title="Registro EPF - Instituto de Genética Humana", layout="wide")

COLUMNAS = [
    "archivo_origen", "Nombres", "Apellido", "DNI", "Telefono", "mail", "Ciudad",
    "Fecha de Nacimiento", "Nombre de la Enfermedad", "Nº ORPHA", "EPOF?", "Genetico?",
    "Tiene estudio confirmatorio", "Archivo confirmatorio", "Observaciones",
    "Se le respondio?", "Quien le respondio", "Estado", "Comentarios", "Tipo de turno",
    "Fecha de turno", "Hospital derivador", "Apellido y nombre solicitante",
    "DNI solicitante", "PARENTESCO",
    # columnas internas de trabajo, no forman parte de la planilla del instituto:
    "_modalidad_atencion", "_es_paciente_confirmado", "_faltantes", "_revisar_manualmente",
]


# ---------- Login simple ----------
def check_password() -> bool:
    def password_entered():
        if st.session_state.get("password") == st.secrets.get("APP_PASSWORD", ""):
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if st.session_state.get("password_correct"):
        return True

    st.text_input("Contraseña de acceso", type="password", on_change=password_entered, key="password")
    if st.session_state.get("password_correct") is False:
        st.error("Contraseña incorrecta")
    return False


if not check_password():
    st.stop()


# ---------- Estado ----------
if "df" not in st.session_state:
    st.session_state.df = pd.DataFrame(columns=COLUMNAS)


def flatten(source_file: str, data: dict) -> dict:
    if "error" in data:
        return {"archivo_origen": source_file, "Observaciones": f"ERROR de extracción: {data['error']}"}

    paciente = data.get("paciente") or {}
    solicitante = data.get("solicitante") or {}

    def join_multi(v):
        return "; ".join(v) if isinstance(v, list) else (v or "")

    adjunto = data.get("adjunto_diagnostico")
    # "Archivo confirmatorio" y "Tiene estudio confirmatorio" en la planilla del
    # instituto son un marcador manual ("archivo") — solo sugerimos, no confirmamos.
    archivo_confirmatorio = "archivo (sugerido, confirmar)" if adjunto else ""
    tiene_estudio = "SI (sugerido, confirmar)" if adjunto else ("NO" if adjunto is False else "")

    return {
        "archivo_origen": source_file,
        "Nombres": paciente.get("nombres"),
        "Apellido": paciente.get("apellido"),
        "DNI": paciente.get("dni"),
        "Telefono": join_multi(paciente.get("telefono")),
        "mail": join_multi(paciente.get("email")),
        "Ciudad": paciente.get("domicilio"),
        "Fecha de Nacimiento": paciente.get("fecha_nacimiento"),
        "Nombre de la Enfermedad": paciente.get("diagnostico"),
        "Nº ORPHA": "",             # lo completa el equipo (clasificación médica)
        "EPOF?": "",                # lo completa el equipo
        "Genetico?": "",            # lo completa el equipo
        "Tiene estudio confirmatorio": tiene_estudio,
        "Archivo confirmatorio": archivo_confirmatorio,
        "Observaciones": "",
        "Se le respondio?": "",
        "Quien le respondio": "",
        "Estado": "Pendiente",
        "Comentarios": "",
        "Tipo de turno": "",
        "Fecha de turno": "",
        "Hospital derivador": "",
        "Apellido y nombre solicitante": solicitante.get("nombre_apellido"),
        "DNI solicitante": solicitante.get("dni"),
        "PARENTESCO": solicitante.get("parentesco"),
        "_modalidad_atencion": data.get("modalidad_atencion"),
        "_es_paciente_confirmado": data.get("es_paciente_confirmado"),
        "_faltantes": join_multi(data.get("faltantes")),
        "_revisar_manualmente": join_multi(data.get("revisar_manualmente")),
    }


def extraer_txts_de_zip(zip_bytes: bytes) -> list[tuple[str, str]]:
    """Devuelve lista de (nombre_archivo, contenido_texto) de los .txt dentro del zip."""
    resultado = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        for name in z.namelist():
            if name.lower().endswith(".txt") and not name.startswith("__MACOSX"):
                with z.open(name) as f:
                    resultado.append((Path(name).name, f.read().decode("utf-8", errors="replace")))
    return resultado


def parsear_texto(nombre: str, contenido: str) -> Conversation:
    """Parsea el contenido de un .txt ya leído en memoria (sin ir a disco)."""
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", encoding="utf-8", delete=False) as tmp:
        tmp.write(contenido)
        tmp_path = Path(tmp.name)
    conv = parse_whatsapp_txt(tmp_path)
    conv.source_file = nombre
    tmp_path.unlink(missing_ok=True)
    return conv


# ---------- UI ----------
st.title("📋 Registro EPF — Instituto de Genética Humana")
st.caption(f"Motor de extracción activo: **{get_provider().capitalize()}** (se cambia en Settings → Secrets, variable `PROVIDER`)")

tab_cargar, tab_datos, tab_stats = st.tabs(["📤 Cargar chats", "📊 Base de datos", "📈 Estadísticas"])

with tab_cargar:
    st.subheader("Subir chats exportados de WhatsApp")
    st.caption("Podés subir un .zip con varios .txt, o archivos .txt sueltos.")

    archivos = st.file_uploader(
        "Chats exportados", type=["txt", "zip"], accept_multiple_files=True
    )

    if archivos and st.button("Procesar chats", type="primary"):
        pendientes = []
        for archivo in archivos:
            contenido = archivo.read()
            if archivo.name.lower().endswith(".zip"):
                pendientes.extend(extraer_txts_de_zip(contenido))
            else:
                pendientes.append((archivo.name, contenido.decode("utf-8", errors="replace")))

        ya_procesados = set(st.session_state.df["archivo_origen"]) if not st.session_state.df.empty else set()
        nuevos = [(n, c) for n, c in pendientes if n not in ya_procesados]

        if not nuevos:
            st.info("Todos los archivos subidos ya estaban procesados en la base.")
        else:
            progreso = st.progress(0.0, text="Procesando...")
            filas_nuevas = []
            errores = []
            for i, (nombre, contenido) in enumerate(nuevos, 1):
                conv = parsear_texto(nombre, contenido)
                try:
                    resultado = extract_from_conversation(conv.full_text, source_file=nombre)
                    filas_nuevas.append(flatten(nombre, resultado.data))
                except Exception as e:
                    errores.append(nombre)
                    filas_nuevas.append({
                        "archivo_origen": nombre,
                        "Observaciones": f"ERROR al procesar: {e}",
                        "Estado": "Error - reintentar",
                    })
                progreso.progress(i / len(nuevos), text=f"Procesando {nombre} ({i}/{len(nuevos)})")

            st.session_state.df = pd.concat(
                [st.session_state.df, pd.DataFrame(filas_nuevas)], ignore_index=True
            )
            progreso.empty()
            st.success(f"{len(filas_nuevas)} chat(s) nuevo(s) procesado(s).")
            if errores:
                st.warning(
                    f"⚠️ {len(errores)} chat(s) no se pudieron procesar tras varios intentos: "
                    f"{', '.join(errores)}. Quedaron marcados en la tabla — podés reintentar "
                    f"subiéndolos de nuevo más tarde."
                )

    st.divider()
    st.subheader("O restaurar desde un Excel guardado antes")
    excel_restaurar = st.file_uploader("Excel de respaldo (.xlsx)", type=["xlsx"], key="restaurar")
    if excel_restaurar and st.button("Restaurar base desde Excel"):
        st.session_state.df = pd.read_excel(excel_restaurar)
        st.success(f"Base restaurada con {len(st.session_state.df)} registros.")

with tab_datos:
    st.subheader("Base de datos del registro")

    if st.session_state.df.empty:
        st.info("Todavía no hay datos cargados. Andá a la pestaña 'Cargar chats'.")
    else:
        col1, col2, col3 = st.columns(3)
        with col1:
            filtro_estado = st.selectbox(
                "Filtrar por estado",
                ["Todos", "Solo incompletos", "Falta adjunto", "Para revisar manualmente"],
            )
        with col2:
            filtro_modalidad = st.selectbox(
                "Filtrar por modalidad",
                ["Todas"] + sorted(st.session_state.df["_modalidad_atencion"].dropna().unique().tolist()),
            )
        with col3:
            busqueda = st.text_input("Buscar por nombre o DNI")

        df_vista = st.session_state.df.copy()

        if filtro_estado == "Solo incompletos":
            df_vista = df_vista[df_vista["_faltantes"].fillna("") != ""]
        elif filtro_estado == "Falta adjunto":
            df_vista = df_vista[df_vista["_faltantes"].str.contains("adjunto", case=False, na=False)]
        elif filtro_estado == "Para revisar manualmente":
            df_vista = df_vista[df_vista["_revisar_manualmente"].fillna("") != ""]

        if filtro_modalidad != "Todas":
            df_vista = df_vista[df_vista["_modalidad_atencion"] == filtro_modalidad]

        if busqueda:
            mask = (
                df_vista["Nombres"].str.cat(df_vista["Apellido"], sep=" ", na_rep="").str.contains(busqueda, case=False, na=False)
                | df_vista["DNI"].astype(str).str.contains(busqueda, case=False, na=False)
            )
            df_vista = df_vista[mask]

        st.caption(f"{len(df_vista)} de {len(st.session_state.df)} registros")

        editado = st.data_editor(
            df_vista, num_rows="dynamic", width="stretch", key="editor_principal"
        )
        if st.button("💾 Guardar cambios de la edición"):
            st.session_state.df.update(editado)
            st.success("Cambios guardados en la sesión.")

        st.divider()
        formato_institucional = st.checkbox(
            "Exportar en formato exacto de la planilla del instituto (sin columnas de ayuda interna)",
            value=True,
        )
        df_exportar = st.session_state.df.copy()
        if formato_institucional:
            df_exportar = df_exportar.drop(columns=[c for c in df_exportar.columns if c.startswith("_")])
        else:
            df_exportar.columns = [c.lstrip("_") for c in df_exportar.columns]

        buffer = io.BytesIO()
        df_exportar.to_excel(buffer, index=False, sheet_name="Registro EPF")
        st.download_button(
            "⬇️ Descargar base completa en Excel",
            data=buffer.getvalue(),
            file_name="registro_epf.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        st.caption(
            "⚠️ Recordá descargar este Excel como respaldo periódicamente: "
            "el almacenamiento de la app puede reiniciarse y perder lo cargado en la sesión."
        )

with tab_stats:
    st.subheader("Estadísticas del registro")

    if st.session_state.df.empty:
        st.info("Todavía no hay datos cargados.")
    else:
        df = st.session_state.df
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total registros", len(df))
        c2.metric("Completos", int((df["_faltantes"].fillna("") == "").sum()))
        c3.metric("Incompletos", int((df["_faltantes"].fillna("") != "").sum()))
        c4.metric(
            "Para revisar",
            int((df["_revisar_manualmente"].fillna("") != "").sum()),
        )

        st.divider()
        col1, col2 = st.columns(2)
        with col1:
            st.write("**Diagnósticos más frecuentes**")
            if df["Nombre de la Enfermedad"].notna().any():
                st.bar_chart(df["Nombre de la Enfermedad"].value_counts().head(10))
        with col2:
            st.write("**Modalidad de atención**")
            if df["_modalidad_atencion"].notna().any():
                st.bar_chart(df["_modalidad_atencion"].value_counts())