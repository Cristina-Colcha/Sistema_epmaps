import os
import traceback # Asegúrate de que esto esté aquí
import pandas as pd
import requests
from flask import Flask, render_template, request, send_file, jsonify, Response
from werkzeug.utils import secure_filename
from datetime import timedelta, datetime
from prophet import Prophet
from dotenv import load_dotenv
import time # Añadir para los delays
load_dotenv()
try:
    from tqdm import tqdm
except ImportError:
    tqdm = lambda x, **kwargs: x

app = Flask(__name__)

# Configuración de la aplicación principal
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

ALLOWED_EXTENSIONS = {'xlsx'}

def allowed_file(filename):
    """Verifica si la extensión del archivo es permitida."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- Funciones de mantenimiento de Sensores ---

def preparar_serie_faltantes(df, estacion):
    """Prepara una serie de tiempo para Prophet con datos faltantes por mes."""
    df_tmp = df[['Fecha', estacion]].copy()
    df_tmp['faltante'] = df_tmp[estacion].isna().astype(int)
    df_tmp['mes'] = df_tmp['Fecha'].dt.to_period('M').dt.to_timestamp()
    total_por_mes = df_tmp.groupby('mes').size()
    faltantes_por_mes = df_tmp.groupby('mes')['faltante'].sum()
    proporcion = (faltantes_por_mes / total_por_mes).reset_index()
    proporcion.columns = ['ds', 'y']
    return proporcion

def predecir_faltantes(serie, umbral=0.01, meses_a_predecir=12):
    if len(serie) < 3:
        return []
    model = Prophet(yearly_seasonality=True, weekly_seasonality=False, daily_seasonality=False)
    model.fit(serie)
    future = model.make_future_dataframe(periods=meses_a_predecir, freq='M')
    forecast = model.predict(future)
    
    hoy = pd.to_datetime(datetime.today().date())
    # CORRECCIÓN DE UNBOUNDLOCALERROR: Usa 'forecast' para el filtro inicial
    predicciones_futuras = forecast[forecast['ds'] > hoy] 
    
    fechas_alerta = predicciones_futuras[predicciones_futuras['yhat'] > umbral]['ds'].dt.strftime('%Y-%m-%d').tolist()
    return fechas_alerta

def detectar_anomalias_y_tendencias(df, estacion, umbral_porcentaje=50):
    """Detecta anomalías en los datos de una estación basándose en la variación porcentual."""
    df_tmp = df[['Fecha', estacion]].dropna().copy()
    df_tmp.sort_values('Fecha', inplace=True)
    if not df_tmp.empty and len(df_tmp) > 1:
        df_tmp['variacion'] = df_tmp[estacion].pct_change() * 100
        df_tmp['tipo'] = df_tmp['variacion'].apply(lambda x: 'anomalía' if pd.notna(x) and abs(x) > umbral_porcentaje else 'normal')
        df_tmp['Fecha_str'] = df_tmp['Fecha'].dt.strftime('%Y-%m-%d')
        anomalias = df_tmp[df_tmp['tipo'] == 'anomalía'][['Fecha_str', 'variacion']].to_dict(orient='records')
        return anomalias
    return []

def generar_reporte_mensual(df, estacion):
    """Genera un reporte mensual resumido para una estación."""
    df_tmp = df[['Fecha', estacion]].copy()
    df_tmp['mes'] = df_tmp['Fecha'].dt.to_period('M').dt.to_timestamp()
    resumen = df_tmp.groupby('mes').agg(total=('Fecha', 'count'),
                                         faltantes=(estacion, lambda x: x.isna().sum()),
                                         promedio=(estacion, 'mean')).reset_index()
    resumen['porcentaje_faltantes'] = (resumen['faltantes'] / resumen['total']) * 100
    return resumen

def generar_recomendaciones(estacion, datos):
    recomendaciones = []

    porcentaje = datos.get('porcentaje', 0)
    fechas_faltantes = datos.get('fechas_faltantes', [])
    anomalias = datos.get('fechas_anomalias', [])
    estado = datos.get('estado', 'ok')
    fechas_mantenimiento = datos.get('fechas_mantenimiento', [])

    if estado == 'critico':
        recomendaciones.append("🔴 Estado crítico: Se requiere una inspección urgente del sensor en campo.")
    elif estado == 'riesgo':
        recomendaciones.append("🟠 Estado de riesgo: Se recomienda mantenimiento preventivo inmediato.")
    elif estado == 'ok':
        recomendaciones.append("🟢 Estado óptimo: Continuar con mantenimiento preventivo regular.")

    if porcentaje > 30:
        recomendaciones.append(f"⚠️ Más del 30% de los datos de {estacion} están faltantes. Esto puede afectar la calidad de los análisis climáticos.")
        recomendaciones.append("📌 Verifica conectividad, batería y ubicación del sensor.")
    elif porcentaje > 10:
        recomendaciones.append(f"📉 Se detectó un {porcentaje:.1f}% de datos faltantes en {estacion}.")
        recomendaciones.append("🔍 Revisar registros para identificar posibles patrones de fallos.")

    if fechas_faltantes:
        ultimas_fechas = ', '.join(fechas_faltantes[:3])
        recomendaciones.append(f"📅 Fechas con datos faltantes: {ultimas_fechas}.")

    if fechas_mantenimiento:
        prox_fecha = fechas_mantenimiento[0]
        recomendaciones.append(f"🛠️ Próximo mantenimiento predictivo recomendado para el sensor {estacion}: {prox_fecha}.")

    if anomalias:
        recomendaciones.append(f"⚠️ Se detectaron {len(anomalias)} anomalías en los datos de {estacion}.")
        muestra = ', '.join([f"{a['Fecha_str']} ({a['variacion']:.1f}%)" for a in anomalias[:3]])
        recomendaciones.append(f"📊 Ejemplos de anomalías: {muestra}.")
        recomendaciones.append("🔧 Validar calibración del sensor y eventos climáticos extremos en esas fechas.")

    recomendaciones.append("📁 Registrar en bitácora todas las acciones realizadas.")
    return recomendaciones

def analizar_excel(filepath):
    """Analiza el archivo Excel para obtener el estado de los sensores."""
    try:
        df = pd.read_excel(filepath, engine='openpyxl')
    except Exception as e:
        print(f"Error al leer el archivo Excel: {e}")
        return {}, "Error al leer el archivo Excel. Asegúrate de que sea un formato válido."

    df.columns = df.columns.str.strip()
    df['Fecha'] = pd.to_datetime(df['Fecha'])
    resultados = {}
    for estacion in ['P42', 'P43', 'P55']:
        if estacion in df.columns:
            datos_faltantes = df[estacion].isna().sum()
            total = df[estacion].shape[0]
            porcentaje = (datos_faltantes / total) * 100
            fechas_faltantes = df[df[estacion].isna()]['Fecha'].dt.strftime('%Y-%m-%d').tolist()
            serie = preparar_serie_faltantes(df, estacion)
            fechas_mantenimiento_predictivas = predecir_faltantes(serie, umbral=0.01)
            anomalias = detectar_anomalias_y_tendencias(df, estacion)
            estado = 'ok'
            if porcentaje > 30 and datos_faltantes > 0:
                estado = 'critico'
            elif porcentaje > 20 or len(anomalias) > 0:
                estado = 'riesgo'

            resultados[estacion] = {
                'total': total,
                'faltantes': datos_faltantes,
                'porcentaje': porcentaje,
                'fechas_faltantes': fechas_faltantes,
                'fechas_mantenimiento': fechas_mantenimiento_predictivas,
                'fechas_anomalias': anomalias,
                'estado': estado,
                'alerta': estado in ['riesgo', 'critico'],
                'reporte_mensual': generar_reporte_mensual(df, estacion).to_dict(orient='records'),
                'recomendaciones': generar_recomendaciones(estacion, {
                    'porcentaje': porcentaje,
                    'fechas_faltantes': fechas_faltantes,
                    'fechas_anomalias': anomalias,
                    'estado': estado,
                    'fechas_mantenimiento': fechas_mantenimiento_predictivas
                })
            }
        else:
            print(f"Advertencia: La columna '{estacion}' no se encontró en el archivo Excel.")
    return resultados, None

# --- Funciones de clima ---

TIMEZONE = 'America/Guayaquil'
SENSORES_COORDS = {
    'P42': {'lat': -0.6022867145410288, 'lon': -78.1986689291808},
    'P43': {'lat': -0.5934839659614135, 'lon': -78.20825370752031},
    'P55': {'lat': -0.5731364867736277, 'lon': -78.138},
}

def consultar_clima(fecha, lat, lon):
    fecha_str = fecha.strftime('%Y-%m-%d')
    url = (
        f"https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={lat}&longitude={lon}"
        f"&start_date={fecha_str}&end_date={fecha_str}"
        f"&daily=precipitation_sum,windspeed_10m_max,temperature_2m_max"
        f"&timezone={TIMEZONE}"
    )
    try:
        r = requests.get(url)
        r.raise_for_status()
        data = r.json()
        if 'daily' in data and data['daily']:
            return {
                "precipitacion_mm": data['daily']['precipitation_sum'][0],
                "viento_max_kmh": data['daily']['windspeed_10m_max'][0],
                "temperatura_max": data['daily']['temperature_2m_max'][0]
            }
        else:
            print(f"Advertencia: Datos incompletos para {fecha_str}.")
            return {"precipitacion_mm": None, "viento_max_kmh": None, "temperatura_max": None}
    except Exception as e:
        print(f"Error consultando clima para {fecha_str}: {e}")
        return {"precipitacion_mm": None, "viento_max_kmh": None, "temperatura_max": None}

global_climate_data_df = None
global_sensor_analysis_results = {}
last_processed_excel_data = []

# --- Rutas de la Aplicación ---

@app.route('/', methods=['GET', 'POST'])
def index():
    """
    Ruta principal para la carga de archivos Excel y visualización de mantenimiento de sensores.
    """
    global global_sensor_analysis_results
    resultados = {}
    error = None
    if request.method == 'POST':
        file = request.files.get('file')
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            resultados, error = analizar_excel(filepath)
            global_sensor_analysis_results = resultados
        else:
            error = "Tipo de archivo no permitido o ningún archivo seleccionado."
    return render_template('index.html', resultados=resultados, error=error)

@app.route('/datos-climaticos')
def datos_climaticos_page():
    global last_processed_excel_data
    upload_folder = os.path.abspath(app.config.get('UPLOAD_FOLDER', 'uploads'))
    os.makedirs(upload_folder, exist_ok=True)

    excel_path_fijo = os.path.join('data', 'Precipitacion_Mensual__P42_P43_P5522062025222139.xlsx')

    df_fijo = pd.DataFrame() # Inicializar como DataFrame vacío
    
    if os.path.exists(excel_path_fijo):
        try:
            df_fijo = pd.read_excel(excel_path_fijo)
            df_fijo['Fecha'] = pd.to_datetime(df_fijo['Fecha'], dayfirst=True)
            print(f"Archivo Excel fijo leído correctamente para datos climáticos. Shape: {df_fijo.shape}")
        except Exception as e:
            print(f"Error al leer el archivo Excel fijo para datos climáticos: {e}")
            traceback.print_exc()
            # Si hay un error al leer el archivo fijo, aún podemos usar los datos procesados anteriormente
            if last_processed_excel_data:
                print("INFO: Usando los últimos datos procesados por Streamlit para la tabla debido a error en archivo fijo.")
                return render_template('resultado.html', datos=last_processed_excel_data)
            else:
                return "Error: El archivo Excel de precipitaciones no se pudo leer y no hay datos previos para mostrar.", 500
    else:
        print(f"Error: Archivo Excel no encontrado en {excel_path_fijo}. No se cargan datos fijos.")
        # Si el archivo fijo no existe, intentamos cargar desde `last_processed_excel_data`
        # si hay datos de una carga anterior por Streamlit.
        if last_processed_excel_data:
            print("INFO: Usando los últimos datos procesados por Streamlit para la tabla.")
            return render_template('resultado.html', datos=last_processed_excel_data)
        else:
            return "Error: El archivo Excel de precipitaciones no se encontró en el servidor y no hay datos previos para mostrar.", 500


    sensores = ['P42', 'P43', 'P55']
    fechas_faltantes = []

    # Solo procesa si df_fijo no está vacío después del intento de carga
    if not df_fijo.empty:
        for sensor in sensores:
            if sensor in df_fijo.columns:
                faltantes = df_fijo[df_fijo[sensor].isna()][['Fecha']].copy()
                faltantes['Sensor'] = sensor
                fechas_faltantes.append(faltantes)
            else:
                print(f"Advertencia: El sensor '{sensor}' no se encontró en las columnas del Excel fijo.")

    if not fechas_faltantes:
        print("INFO: No hay datos faltantes en el archivo Excel fijo o el archivo está vacío. Mostrando tabla vacía.")
        # Si no hay faltantes, aún podemos mostrar una tabla vacía o los últimos datos procesados
        if last_processed_excel_data:
            return render_template('resultado.html', datos=last_processed_excel_data)
        else:
            return render_template('resultado.html', datos=[])

    faltantes_total = pd.concat(fechas_faltantes).reset_index(drop=True)
    faltantes_total = faltantes_total.drop_duplicates(subset=['Fecha', 'Sensor']).reset_index(drop=True)

    climas = []
    print(f"Consultando clima para {len(faltantes_total)} fechas con datos faltantes (desde archivo fijo)...")
    for _, row in tqdm(faltantes_total.iterrows(), total=len(faltantes_total), desc="Consultando clima"):
        coords = SENSORES_COORDS.get(row['Sensor'])
        if coords:
            clima = consultar_clima(row['Fecha'], coords['lat'], coords['lon'])
        else:
            clima = {"precipitacion_mm": None, "viento_max_kmh": None, "temperatura_max": None}
        clima['Fecha'] = row['Fecha']
        clima['Sensor'] = row['Sensor']
        climas.append(clima)
        time.sleep(0.1) # Pausa para evitar rate limits

    df_clima = pd.DataFrame(climas)

    faltantes_total['Fecha'] = pd.to_datetime(faltantes_total['Fecha'])
    df_clima['Fecha'] = pd.to_datetime(df_clima['Fecha'])

    resultado_df = pd.merge(faltantes_total, df_clima, on=['Fecha', 'Sensor'], how='left')
    resultado_df = resultado_df.sort_values(['Sensor', 'Fecha']).reset_index(drop=True)
    resultado_df.set_index('Fecha', inplace=True)

    for col in ['precipitacion_mm', 'viento_max_kmh', 'temperatura_max']:
        resultado_df[col] = pd.to_numeric(resultado_df[col], errors='coerce')
        resultado_df[col] = resultado_df.groupby('Sensor')[col].transform(
            lambda x: x.interpolate(method='time').ffill().bfill()
        )

    resultado_df.reset_index(inplace=True)

    datos_para_tabla = resultado_df.to_dict(orient='records')
    last_processed_excel_data = datos_para_tabla # Guardar para futuras cargas

    output_excel_path_fijo = os.path.join(upload_folder, 'faltantes_resultado.xlsx')
    
    try:
        with pd.ExcelWriter(output_excel_path_fijo, engine='xlsxwriter') as writer:
            df_fijo.to_excel(writer, sheet_name='Original', index=False)

            df_completado_filas = df_fijo.copy()
            if not resultado_df.empty:
                for _, row in resultado_df.iterrows():
                    fecha = row['Fecha']
                    sensor = row['Sensor']
                    valor_precipitacion = row['precipitacion_mm']
                    if pd.notna(valor_precipitacion) and \
                       fecha in df_completado_filas['Fecha'].values and \
                       sensor in df_completado_filas.columns:
                        df_completado_filas.loc[df_completado_filas['Fecha'] == fecha, sensor] = valor_precipitacion

            df_completado_filas.to_excel(writer, sheet_name='Completado_Filas', index=False)
            resultado_df.to_excel(writer, sheet_name='Detalle_Clima_Relleno', index=False)

        print(f"Archivo Excel guardado correctamente en {output_excel_path_fijo}")
    except Exception as e:
        print(f"Error al guardar el archivo Excel de resultados en datos_climaticos_page: {e}")
        traceback.print_exc()

    return render_template('resultado.html', datos=datos_para_tabla)


@app.route('/descargar_faltantes')
def descargar_faltantes():
    upload_folder = os.path.abspath(app.config.get('UPLOAD_FOLDER', 'uploads'))
    file_path = os.path.join(upload_folder, 'faltantes_resultado.xlsx')
    if os.path.exists(file_path):
        return send_file(file_path, as_attachment=True, download_name="faltantes_clima.xlsx")
    else:
        return 'Archivo no encontrado. Por favor, genera el reporte primero.', 404

@app.route('/descargar_procesado/<filename>')
def descargar_procesado(filename):
    upload_folder = os.path.abspath(app.config.get('UPLOAD_FOLDER', 'uploads'))
    file_path = os.path.join(upload_folder, filename)
    if os.path.exists(file_path):
        return send_file(file_path, as_attachment=True, download_name=filename)
    else:
        return 'Archivo no encontrado.', 404

@app.route('/ask-clima-bot', methods=['POST'])
def ask_clima_bot():
    user_query = request.json.get('query')
    if not user_query:
        return jsonify({"response": "Por favor, ingresa una pregunta."}), 400

    global global_climate_data_df
    global global_sensor_analysis_results

    project_hypothesis = "El desarrollo e implementación de un sistema unificado para el monitoreo de sensores y la integración de datos climáticos reducirá el tiempo de detección de anomalías y datos faltantes en los sensores, y mejorará la capacidad de los usuarios para tomar decisiones informadas sobre el mantenimiento preventivo y correctivo, al proporcionar un acceso rápido y contextualizado a la información climática relevante."

    resumen_generado_por_sistema_parts = []
    resumen_generado_por_sistema_parts.append(f"Contexto del Proyecto (Hipótesis General): {project_hypothesis}")

    if global_climate_data_df is not None and not global_climate_data_df.empty:
        data_string_clima = global_climate_data_df.to_string(index=False, max_rows=50, max_colwidth=50)
        resumen_generado_por_sistema_parts.append(f"Datos climáticos históricos disponibles (Fechas sin datos con clima registrado):\n{data_string_clima}")
    else:
        resumen_generado_por_sistema_parts.append("No hay datos climáticos históricos cargados para consultar.")

    if global_sensor_analysis_results:
        sensor_details_list = []
        for estacion, data in global_sensor_analysis_results.items():
            anomalies_info = f"Anomalías detectadas: {len(data['fechas_anomalias'])}."
            if data['fechas_anomalias']:
                anomalies_sample = data['fechas_anomalias'][:3]
                anomalies_info += f" Ejemplos: {', '.join([f'{a['Fecha_str']} (Var: {a['variacion']:.2f}%)' for a in anomalies_sample])}"
                if len(data['fechas_anomalias']) > 3:
                    anomalies_info += "..."

            sensor_details_list.append(
                f"--- Estación {estacion} ---\n"
                f"  - Registros totales: {data['total']}\n"
                f"  - Datos faltantes: {data['faltantes']} ({data['porcentaje']:.2f}%)\n"
                f"  - Estado del sensor: {data['estado']}\n"
                f"  - Fechas con datos faltantes: {', '.join(data['fechas_faltantes']) if data['fechas_faltantes'] else 'Ninguna'}\n"
                f"  - {anomalies_info}\n"
                f"  - Recomendaciones actuales del sistema: {', '.join(data['recomendaciones']) if data['recomendaciones'] else 'Ninguna'}"
            )
        resumen_generado_por_sistema_parts.append(f"Resultados del análisis de sensores:\n" + "\n\n".join(sensor_details_list))
    else:
        resumen_generado_por_sistema_parts.append("No hay resultados de análisis de sensores cargados. Por favor, sube un archivo Excel en la página principal.")

    resumen_generado_por_sistema_context = "\n\n".join(resumen_generado_por_sistema_parts)

    prompt = f"""Eres un ingeniero en mantenimiento predictivo especializado en sistemas de sensores ambientales.
    Tu objetivo es analizar los datos y el contexto proporcionados para responder a las preguntas del usuario de manera profesional y técnica.

    Aquí tienes el resumen técnico generado por el sistema y el contexto relevante:

    {resumen_generado_por_sistema_context}

    Pregunta del usuario: {user_query}

    Por favor, responde la pregunta del usuario basándote estrictamente en la información proporcionada en el contexto y tu conocimiento como Ingeniero en mantenimiento predictivo.

    **Instrucciones Específicas:**
    1.  **Si la pregunta es sobre la hipótesis del proyecto:** Responde directamente basándote en la "Hipótesis General" proporcionada.
    2.  **Si la pregunta es sobre datos faltantes o anomalías:**
        * Analiza el "porqué" de los datos faltantes o anomalías, basándote en el contexto (ej. estado del sensor, fechas faltantes, anomalías detectadas, datos climáticos) o en conocimientos generales de tu campo (posibles causas como fallos de sensor, problemas de comunicación, condiciones climáticas extremas, vandalismo, obstrucciones, batería baja, etc.).
        * Si el porcentaje de datos faltantes para una estación supera el 30%, menciona las posibles consecuencias si no se corrige la situación (ej. pérdida de representatividad de los datos, decisiones erróneas en la gestión de recursos hídricos, riesgos operacionales, fallos en la predicción de eventos climáticos, impacto en la calibración de modelos).
        * Incluye al final una recomendación específica si es necesario reubicar o revisar el sensor afectado, o realizar un mantenimiento preventivo/correctivo detallado.
    3.  **Si la pregunta es sobre definiciones de términos técnicos:** Proporciona una definición clara y concisa de conceptos como 'sensor', 'precipitación', 'viento', 'temperatura', 'monitoreo hidráulico', 'mantenimiento predictivo', 'anomalía', 'calibración', 'telemetría', etc.
    4.  **Tono:** Redacta tus respuestas en un tono formal y técnico, como si fuera un informe dirigido a un comité de auditoría o gerencia de operaciones. Justifica tus conclusiones.
    5.  **Limitación:** Si la pregunta no se puede responder con la información dada, indica claramente que la información no está disponible en el contexto o que escapa a tu rol.

    Prioriza la información numérica o fáctica si es relevante.
    """

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        print("Error: La clave API de Gemini (GEMINI_API_KEY) no está configurada en el servidor.")
        return jsonify({"response": "Error interno: La clave API del bot no está configurada."}), 500

    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"

    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 800
        }
    }

    try:
        response = requests.post(api_url, headers={'Content-Type': 'application/json'}, json=payload)
        response.raise_for_status()
        result = response.json()

        bot_response = "Lo siento, no pude generar una respuesta en este momento."
        if result and result.get('candidates') and result['candidates'][0].get('content') and result['candidates'][0]['content'].get('parts'):
            bot_response = result['candidates'][0]['content']['parts'][0]['text']

        return jsonify({"response": bot_response})
    except requests.exceptions.RequestException as e:
        print(f"Error al llamar a la API de Gemini: {e}")
        return jsonify({"response": "Lo siento, hubo un error de conexión al intentar comunicarme con el bot."}), 500
    except Exception as e:
        print(f"Error inesperado en la función ask_clima_bot: {e}")
        return jsonify({"response": "Lo siento, ocurrió un error interno al procesar tu solicitud."}), 500


port = int(os.environ.get("PORT", 5000))
app.run(host="0.0.0.0", port=port, debug=True)
