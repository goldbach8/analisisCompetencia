import streamlit as st
import pandas as pd
import re
import os

DB_FILE = "master_database.csv"
REQUIRED_COLUMNS_BASE = [
    "Fecha", "Importador", "País de Origen", "País de Procedencia", 
    "Moneda Divisa", "Unitario Divisa", "FOB Divisa", "Marca o Descripcion",
    "Marca - Sufijos"
]

def extract_and_clean_code(text):
    if pd.isna(text):
        return None
    
    text = str(text)
    match_ai = re.search(r'AI\((.*?)\)', text)
    match_ab = re.search(r'AB\((.*?)\)', text)
    
    if match_ai:
        raw_code = match_ai.group(1)
    elif match_ab:
        raw_code = match_ab.group(1)
    else:
        return None
        
    cleaned_code = re.sub(r'[\.\,\/\s]', '', raw_code)
    return cleaned_code

def load_database():
    if os.path.exists(DB_FILE):
        df = pd.read_csv(DB_FILE, parse_dates=["Fecha"])
        return df
    return pd.DataFrame(columns=REQUIRED_COLUMNS_BASE + ["Cantidad", "CodigoProducto"])

def save_database(df):
    df.to_csv(DB_FILE, index=False)

st.set_page_config(page_title="Softrade Analytics", layout="wide")
st.title("Gestor de Archivos Softrade")

tab_carga, tab_consulta = st.tabs(["Carga de Datos", "Consulta de Productos"])

with tab_carga:
    st.header("Carga y Procesamiento de Archivos Excel")
    uploaded_files = st.file_uploader("Sube uno o más archivos Softrade (.xlsx, .csv)", type=["xlsx", "csv"], accept_multiple_files=True)
    
    if st.button("Procesar y Guardar Archivos"):
        if uploaded_files:
            db_df = load_database()
            new_records_list = []
            
            for file in uploaded_files:
                try:
                    if file.name.endswith('.csv'):
                        df_temp = pd.read_csv(file)
                    else:
                        df_temp = pd.read_excel(file)
                    
                    columnas_leidas = list(df_temp.columns)
                    missing_cols = [col for col in REQUIRED_COLUMNS_BASE if col not in columnas_leidas]
                    
                    if missing_cols:
                        st.error(f"El archivo {file.name} no contiene las columnas base: {missing_cols}")
                        continue
                        
                    idx_unitario = columnas_leidas.index("Unitario Divisa")
                    if idx_unitario == 0:
                        st.error(f"En el archivo {file.name}, 'Unitario Divisa' es la primer columna. No hay cantidad a su izquierda.")
                        continue
                        
                    col_cantidad_objetivo = columnas_leidas[idx_unitario - 1]
                    
                    columnas_mantener = REQUIRED_COLUMNS_BASE + [col_cantidad_objetivo]
                    df_temp = df_temp[columnas_mantener].copy()
                    df_temp = df_temp.rename(columns={col_cantidad_objetivo: "Cantidad"})
                    
                    df_temp["Cantidad"] = pd.to_numeric(df_temp["Cantidad"], errors='coerce').fillna(0).astype(int)
                    df_temp["Unitario Divisa"] = pd.to_numeric(df_temp["Unitario Divisa"], errors='coerce').fillna(0)
                    
                    df_temp["CodigoProducto"] = df_temp["Marca o Descripcion"].apply(extract_and_clean_code)
                    df_temp = df_temp.dropna(subset=["CodigoProducto"])
                    df_temp["Fecha"] = pd.to_datetime(df_temp["Fecha"], errors='coerce')
                    
                    new_records_list.append(df_temp)
                    st.success(f"Archivo {file.name} procesado correctamente.")
                    
                except Exception as e:
                    st.error(f"Error procesando el archivo {file.name}: {e}")
            
            if new_records_list:
                df_nuevos = pd.concat(new_records_list, ignore_index=True)
                db_df = pd.concat([db_df, df_nuevos], ignore_index=True)
                
                initial_count = len(db_df)
                db_df = db_df.drop_duplicates()
                final_count = len(db_df)
                
                save_database(db_df)
                st.info(f"Se añadieron registros. Base total: {final_count} registros ({initial_count - final_count} duplicados omitidos).")
                
        else:
            st.warning("Por favor, sube al menos un archivo.")

with tab_consulta:
    st.header("Consulta de Resumen por Producto")
    db_df = load_database()
    
    if db_df.empty:
        st.warning("La base de datos está vacía. Carga archivos primero.")
    else:
        col1, col2, col3 = st.columns(3)
        with col1:
            codigo_query = st.text_input("Código de Producto (Exacto o Parcial)").strip()
        with col2:
            importadores_disponibles = sorted(db_df["Importador"].dropna().unique().tolist())
            importador_filter = st.multiselect("Filtrar por Importador", options=importadores_disponibles)
        with col3:
            min_date, max_date = db_df["Fecha"].min(), db_df["Fecha"].max()
            date_range = st.date_input("Rango de Fecha", value=(min_date, max_date))

        if st.button("Buscar"):
            if not codigo_query:
                st.warning("Introduce un código de producto para buscar.")
            else:
                mask = db_df["CodigoProducto"].str.contains(codigo_query, case=False, na=False)
                
                if importador_filter:
                    mask &= db_df["Importador"].isin(importador_filter)
                
                if len(date_range) == 2:
                    start_date, end_date = date_range
                    mask &= (db_df["Fecha"].dt.date >= start_date) & (db_df["Fecha"].dt.date <= end_date)
                    
                df_filtered = db_df[mask].copy()
                
                if df_filtered.empty:
                    st.info("No se encontraron registros para los filtros seleccionados.")
                else:
                    df_filtered['Valor_Total_Fila'] = df_filtered['Unitario Divisa'] * df_filtered['Cantidad']
                    
                    st.subheader("Resumen General")
                    
                    # Agrupación compuesta por importador y divisa
                    agrupacion_base = ["Importador", "Moneda Divisa"]
                    
                    idx_min = df_filtered.groupby(agrupacion_base)['Unitario Divisa'].idxmin()
                    df_min_prices = df_filtered.loc[idx_min, agrupacion_base + ['Marca - Sufijos', 'Unitario Divisa', 'Fecha', 'País de Origen']]
                    
                    df_agg = df_filtered.groupby(agrupacion_base).apply(
                        lambda x: pd.Series({
                            'Unidades_Totales': x['Cantidad'].sum(),
                            'Precio_Promedio': x['Valor_Total_Fila'].sum() / x['Cantidad'].sum() if x['Cantidad'].sum() > 0 else 0
                        })
                    ).reset_index()
                    
                    resumen = pd.merge(df_agg, df_min_prices, on=agrupacion_base)
                    resumen["Fecha"] = resumen["Fecha"].dt.strftime('%d/%m/%Y')
                    
                    resumen = resumen.rename(columns={
                        "Importador": "Empresa Importadora",
                        "Moneda Divisa": "Divisa",
                        "Marca - Sufijos": "Marca",
                        "Unidades_Totales": "Unidades totales compradas (en rango)",
                        "Unitario Divisa": "Precio Mínimo Registrado",
                        "Precio_Promedio": "Precio Promedio",
                        "Fecha": "Fecha de Compra Mínima",
                        "País de Origen": "País de Compra Mínima"
                    })
                    
                    column_order = [
                        "Empresa Importadora", "Marca", "Divisa", "Unidades totales compradas (en rango)",
                        "Precio Promedio", "Precio Mínimo Registrado", 
                        "Fecha de Compra Mínima", "País de Compra Mínima"
                    ]
                    resumen = resumen[column_order]
                    
                    # Formateo sin símbolo fijo de moneda (depende de la columna Divisa)
                    formato_resumen = {
                        "Unidades totales compradas (en rango)": "{:,.0f}",
                        "Precio Promedio": "{:,.2f}",
                        "Precio Mínimo Registrado": "{:,.2f}"
                    }
                    
                    st.dataframe(resumen.style.format(formato_resumen), use_container_width=True, hide_index=True)
                    
                    st.subheader("Registros Detallados")
                    
                    df_display = df_filtered.drop(columns=['Valor_Total_Fila']).copy()
                    df_display["Fecha"] = df_display["Fecha"].dt.strftime('%d/%m/%Y')
                    
                    # Diccionario con el precio mínimo local para cada divisa
                    minimos_por_divisa = df_display.groupby('Moneda Divisa')['Unitario Divisa'].min().to_dict()
                    
                    def highlight_min_row(row):
                        divisa = row['Moneda Divisa']
                        # Se resalta si el precio de la fila es igual al mínimo registrado para su divisa
                        if row['Unitario Divisa'] == minimos_por_divisa.get(divisa):
                            return ['background-color: rgba(46, 204, 113, 0.3)'] * len(row)
                        return [''] * len(row)
                    
                    formato_detalle = {
                        "Cantidad": "{:,.0f}",
                        "Unitario Divisa": "{:,.2f}",
                        "FOB Divisa": "{:,.2f}"
                    }
                    
                    styled_df = df_display.style.apply(highlight_min_row, axis=1).format(formato_detalle)
                    st.dataframe(styled_df, use_container_width=True, hide_index=True)