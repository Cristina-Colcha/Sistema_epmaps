import os 
import textwrap
from dotenv import load_dotenv
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from langchain_google_genai import ChatGoogleGenerativeAI

load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
AI_MODEL = "gemini-2.5-flash"
llm = ChatGoogleGenerativeAI(model=AI_MODEL, google_api_key=GOOGLE_API_KEY)

st.set_page_config(layout="wide")
st.title("📊 Estadísticas de Sensores")

archivo = st.file_uploader("📁 Sube el archivo Excel", type=["xlsx"])
if archivo:
    hoja = st.selectbox("Selecciona la hoja", ["Original", "Completado_Filas"])
    df = pd.read_excel(archivo, sheet_name=hoja)

    if 'Fecha' in df.columns:
        df['Fecha'] = pd.to_datetime(df['Fecha'], errors='coerce')
        df['Año'] = df['Fecha'].dt.year
        df['AñoMes'] = df['Fecha'].dt.to_period('M').astype(str)
        df['Mes'] = df['Fecha'].dt.month

        # --- Mejora 1: Resumen de calidad de datos ---
        st.subheader(" Resumen de Calidad de Datos")
        col_q1, col_q2 = st.columns(2)
        with col_q2:
            st.markdown('<h4 style="text-align: center;">📈 Estadísticas Descriptivas</h4>', unsafe_allow_html=True)
            st.write(df[["P42", "P43", "P55"]].describe())


        # --- Mejora 2: Filtro por rango de fechas ---
        st.markdown("---")
        st.subheader("📅 Filtro por Rango de Fechas")
        min_date = df['Fecha'].min().to_pydatetime()
        max_date = df['Fecha'].max().to_pydatetime()
        rango = st.slider(
            "Selecciona un rango de fechas",
            min_value=min_date,
            max_value=max_date,
            value=(min_date, max_date),
            format="YYYY-MM-DD"
        )
        df = df[(df['Fecha'] >= rango[0]) & (df['Fecha'] <= rango[1])]

        # Menú lateral
        opcion = st.sidebar.radio("📂 Selecciona una sección para visualizar", [
            "Métricas Totales",
            "Gráfico Combinado por Mes",
            "Promedios Mensuales",
            "Máximos y Mínimos",
            "Distribución",
            "Proporción Total",
            "Anomalías por Sensor",
            "Estacionalidad Mensual",
        ])

        # Función para detectar anomalías
        def detectar_anomalias(sensor):
            media = df[sensor].mean()
            std = df[sensor].std()
            df[f"{sensor}_Anomalia"] = ((df[sensor] > media + 2*std) | (df[sensor] < media - 2*std))
            return df[df[f"{sensor}_Anomalia"]][["Fecha", sensor]].reset_index(drop=True)

        # Comparación de hojas con IA
        st.sidebar.markdown("---")
        st.sidebar.header("📋 Comparación de Datos")
        if st.sidebar.button("📊 Generar Comparación"):
            with st.spinner("Analizando los datos..."):
                try:
                    df_original = pd.read_excel(archivo, sheet_name="Original")
                    df_completado = pd.read_excel(archivo, sheet_name="Completado_Filas")
                except Exception as e:
                    st.sidebar.error(f"Error al leer hojas: {e}")
                    st.stop()

                for df_temp in [df_original, df_completado]:
                    if 'Fecha' in df_temp.columns:
                        df_temp['Fecha'] = pd.to_datetime(df_temp['Fecha'], errors='coerce')

                def resumen(df_tmp, nombre):
                    return f"""
📄 **{nombre}**
- Fechas: desde {df_tmp['Fecha'].min().strftime('%Y-%m-%d')} hasta {df_tmp['Fecha'].max().strftime('%Y-%m-%d')}
- Suma P42: {df_tmp['P42'].sum():,.2f}
- Suma P43: {df_tmp['P43'].sum():,.2f}
- Suma P55: {df_tmp['P55'].sum():,.2f}
- Promedio P42: {df_tmp['P42'].mean():,.2f}
- Promedio P43: {df_tmp['P43'].mean():,.2f}
- Promedio P55: {df_tmp['P55'].mean():,.2f}
"""

                resumen_original = resumen(df_original, "Original")
                resumen_completado = resumen(df_completado, "Completado_Filas")

                prompt_comparativo = textwrap.dedent(f"""
                Tengo dos hojas de un archivo Excel con datos históricos de sensores del volcán Antisana: una hoja llamada "Original" y otra llamada "Completado_Filas".

                La hoja "Original" contiene los datos base, mientras que la hoja "Completado_Filas" incluye datos completados o corregidos para mejorar el registro.

                A continuación, te presento un resumen estadístico de cada hoja:

                {resumen_original}

                {resumen_completado}

                El objetivo es utilizar los datos de la hoja "Completado_Filas" para mejorar el sistema de mantenimiento preventivo de los sensores del Antisana y evitar posibles desastres derivados de fallos o datos incompletos.

                Por favor, genera una conclusión general comparativa que incluya:

                - Principales diferencias y tendencias entre ambas hojas.
                - Identificación de mejoras significativas en la calidad o consistencia de los datos.
                - Potenciales problemas o áreas donde aún se puede mejorar el sistema.
                - Recomendaciones prácticas para optimizar el mantenimiento y garantizar la fiabilidad de los sensores basándote en los datos.
                - Cómo estas mejoras podrían ayudar a prevenir fallos o desastres futuros.
                Considerar en la conclusion no decir hojas , sino "datos originales" y "datos completados".
                """)
                conclusion_comparativa = llm.predict(prompt_comparativo)
                st.sidebar.markdown("### 🤖 Conclusión:")
                st.sidebar.write(conclusion_comparativa)

        # --- Visualizaciones ---
        if opcion == "Métricas Totales":
            st.subheader("📍 Métricas Totales")
            col1, col2, col3 = st.columns(3)
            col1.metric("Suma de P42", f"{df['P42'].sum():,.2f} mil")
            col2.metric("Suma de P43", f"{df['P43'].sum():,.2f} mil")
            col3.metric("Suma de P55", f"{df['P55'].sum():,.2f} mil")
            st.info("📌 Esta sección muestra la suma total de cada sensor durante todo el período de tiempo.")

        elif opcion == "Gráfico Combinado por Mes":
            st.subheader("📊 Tendencia mensual combinada")
            df_mes = df.groupby("AñoMes")[["P42", "P43", "P55"]].sum().reset_index()
            df_mes = df_mes.sort_values("AñoMes")
            df_mes[["P42", "P43", "P55"]] = df_mes[["P42", "P43", "P55"]].replace(0, pd.NA)
            fig = px.line(df_mes, x="AñoMes", y=["P42", "P43", "P55"],
                          title="Suma mensual de sensores (líneas se cortan con 0s)")
            st.plotly_chart(fig, use_container_width=True)

        elif opcion == "Promedios Mensuales":
            st.subheader("📉 Promedio mensual por sensor")
            df_prom = df.groupby("AñoMes")[["P42", "P43", "P55"]].mean().reset_index()
            df_prom_long = pd.melt(df_prom, id_vars="AñoMes", value_vars=["P42", "P43", "P55"],
                                   var_name="Sensor", value_name="Promedio")
            fig_prom = px.line(df_prom_long, x="AñoMes", y="Promedio", color="Sensor",
                               markers=True, title="Promedio mensual de cada sensor")
            st.plotly_chart(fig_prom, use_container_width=True)

        elif opcion == "Máximos y Mínimos":
            st.subheader("📈 Máximos y mínimos por sensor")
            cols_maxmin = st.columns(3)
            for i, sensor in enumerate(["P42", "P43", "P55"]):
                max_val = df[sensor].max()
                min_val = df[sensor].min()
                fecha_max = df.loc[df[sensor] == max_val, "Fecha"].dt.strftime('%Y-%m').values[0]
                fecha_min = df.loc[df[sensor] == min_val, "Fecha"].dt.strftime('%Y-%m').values[0]
                cols_maxmin[i].markdown(f"""
                ### {sensor}
                🔺 **Máx**: {max_val:,.2f} en `{fecha_max}`  
                🔻 **Mín**: {min_val:,.2f} en `{fecha_min}`
                """)

        elif opcion == "Distribución":
            st.subheader("📊 Distribución de valores por sensor")
            col_hist1, col_hist2, col_hist3 = st.columns(3)
            with col_hist1:
                st.plotly_chart(px.histogram(df, x="P42", nbins=20, title="Distribución P42"), use_container_width=True)
            with col_hist2:
                st.plotly_chart(px.histogram(df, x="P43", nbins=20, title="Distribución P43"), use_container_width=True)
            with col_hist3:
                st.plotly_chart(px.histogram(df, x="P55", nbins=20, title="Distribución P55"), use_container_width=True)

        elif opcion == "Proporción Total":
            st.subheader("📌 Porcentaje que representa cada sensor del total")
            total = df[["P42", "P43", "P55"]].sum()
            fig_pie = px.pie(
                names=total.index,
                values=total.values,
                title="Proporción del total por sensor",
                color_discrete_sequence=px.colors.qualitative.Set2
            )
            st.plotly_chart(fig_pie, use_container_width=True)

        elif opcion == "Anomalías por Sensor":
            st.subheader("🚨 Anomalías Detectadas")
            for sensor in ["P42", "P43", "P55"]:
                df_anom = detectar_anomalias(sensor)
                st.markdown(f"### Sensor {sensor}")
                if df_anom.empty:
                    st.write("No se detectaron anomalías significativas.")
                else:
                    st.dataframe(df_anom, use_container_width=True)

        elif opcion == "Estacionalidad Mensual":
            st.subheader("📅 Estacionalidad Mensual (Promedios)")
            df_mes = df.groupby("Mes")[["P42", "P43", "P55"]].mean().reset_index()
            fig = px.line(df_mes, x="Mes", y=["P42", "P43", "P55"], markers=True,
                          title="Promedios mensuales por sensor")
            st.plotly_chart(fig, use_container_width=True)

        # --- Conclusión Individual por Sección ---
        st.markdown("---")
        st.header("🤖 Conclusión de sección")

        opcion_actual = opcion  # La opción seleccionada en el menú lateral

        if st.button("📝 Generar Conclusión"):
            with st.spinner("Generando conclusión con IA..."):
                prompt_intro = f"""
Estoy analizando datos de precipitación provenientes de sensores pluviométricos y meteorológicos ubicados en el Antisana.
El rango de fechas va desde {df['Fecha'].min().strftime('%Y-%m-%d')} hasta {df['Fecha'].max().strftime('%Y-%m-%d')}.
"""

                if opcion_actual == "Métricas Totales":
                    prompt = prompt_intro + f"""
Las sumas totales de precipitación registradas por los sensores son:
- P42: {df['P42'].sum():,.2f}
- P43: {df['P43'].sum():,.2f}
- P55: {df['P55'].sum():,.2f}

Por favor, genera una conclusión sobre el comportamiento total de los sensores.
"""
                if opcion_actual == "Gráfico Combinado por Mes":
                    prompt = prompt_intro + f"""
Esta estadistica muestra la tendencia mensual de precipitación combinada de los sensores P42, P43 y P55.
Los datos se agruparon por mes y año, y se sumaron las precipitaciones de cada sensor.
Por favor, analiza las tendencias y patrones observados en el gráfico.
Por favor, genera una conclusión sobre el comportamiento total de los sensores.
"""
                elif opcion_actual == "Promedios Mensuales":
                    mensual = df.groupby(df["Fecha"].dt.month).mean(numeric_only=True)
                    prompt = prompt_intro + f"""
Los promedios mensuales por sensor son:
{mensual.round(2).to_string()}

Describe las tendencias de precipitación a lo largo de los meses y posibles patrones estacionales.
"""
                elif opcion_actual == "Máximos y Mínimos":
                    maximos = df[["P42", "P43", "P55"]].max()
                    minimos = df[["P42", "P43", "P55"]].min()
                    prompt = prompt_intro + f"""
Los valores máximos registrados fueron:
{maximos.to_string()}

Los valores mínimos registrados fueron:
{minimos.to_string()}

Resume las observaciones relevantes de los extremos de precipitación.
"""
                elif opcion_actual == "Distribución":
                    prompt = prompt_intro + """
Se ha visualizado la distribución de los datos por sensor.
Comenta sobre la forma de las distribuciones, si hay asimetrías, sesgos o valores atípicos.
"""
                elif opcion_actual == "Proporción Total":
                    total = df[["P42", "P43", "P55"]].sum()
                    total_global = total.sum()
                    proporciones = (total / total_global * 100).round(2)
                    prompt = prompt_intro + f"""
Las proporciones totales de precipitación por sensor son:
{proporciones.to_string()} %

Genera una conclusión sobre la contribución relativa de cada sensor al total.
"""
                elif opcion_actual == "Anomalías por Sensor":
                    prompt = prompt_intro + """
Se ha identificado la presencia de anomalías en los datos de uno o varios sensores.
Describe qué podría indicar esto y qué acciones o análisis podrían ser relevantes.
"""

                elif opcion_actual == "Estacionalidad Mensual":
                    prompt = prompt_intro + """
Se analizó la estacionalidad mensual de los datos.
Describe los patrones que se repiten a lo largo de los años y cómo varía la precipitación.
"""
                elif opcion_actual == "Gráfico Combinado por Mes":
                    prompt = prompt_intro + """
Se ha generado un gráfico combinado mensual para todos los sensores.
Describe cómo se comportan conjuntamente los sensores y si hay correlaciones visibles.
"""
                else:
                    prompt = prompt_intro + """
No se ha seleccionado una sección específica. No hay datos adicionales disponibles.
"""

                conclusion = llm.predict(textwrap.dedent(prompt))
                st.write(conclusion)
