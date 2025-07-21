import os
import pandas as pd
import requests
from flask import Flask, render_template, request, send_file, jsonify, Response # Importamos Response para descargar archivos
from werkzeug.utils import secure_filename
from datetime import timedelta, datetime
from prophet import Prophet # Asegúrate de que Prophet esté instalado si lo vas a usar

# Importar y cargar dotenv
from dotenv import load_dotenv
load_dotenv() # Esto cargará las variables del archivo .env

# Para la barra de progreso en consola (tqdm), no es estrictamente necesario en producción pero útil para depuración
try:
    from tqdm import tqdm
except ImportError:
    tqdm = lambda x, **kwargs: x # Función dummy si tqdm no está instalado

app = Flask(__name__)

# Configuración de la aplicación principal
app.config['UPLOAD_FOLDER'] = 'uploads' # Esta carpeta será efímera en Render
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024 # Límite de tamaño de archivo

# Asegurarse de que la carpeta 'uploads' exista (especialmente para guardar el resultado temporal)
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

ALLOWED_EXTENSIONS = {'xlsx'}

def allowed_file(filename):
    """Verifica si la extensión del archivo es permitida."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- Funciones de app.py original (Mantenimiento de Sensores) ---

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

# La función predecir_faltantes está comentada en tu código original, la mantengo así.
# def predecir_faltantes(serie, umbral=0.01, meses_a_predecir=12):
#     if len(serie) < 3:
#         return []
#     model = Prophet(yearly_seasonality=True, weekly_seasonality=False, daily_seasonality=False)
#     model.fit(serie)
#     future = model.make_future_dataframe(periods=meses_a_predecir, freq='M')
#     forecast = model.predict(future)
#     hoy = pd.to_datetime(datetime.today().date())
#     predicciones_futuras = forecast[forecast['ds'] > hoy]
#     fechas_alerta = predicciones_futuras[predicciones_futuras['yhat'] > umbral]['ds'].dt.strftime('%Y-%m-%d').tolist()
#     return fechas_alerta

def detectar_anomalias_y_tendencias(df, estacion, umbral_porcentaje=50):
    """Detecta anomalías en los datos de una estación basándose en la variación porcentual."""
    df_tmp = df[['Fecha', estacion]].dropna().copy()
    df_tmp.sort_values('Fecha', inplace=True)
    if not df_tmp.empty and len(df_tmp) > 1: # Asegurarse de que haya suficientes datos para calcular la variación
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

def generar_recomendaciones(estado):
    """Genera recomendaciones basadas en el estado del sensor."""
    if estado == 'critico':
        return [
            "✅ Realizar inspección urgente del sensor en campo.",
            "🔌 Verificar energía, conectividad y funcionamiento de componentes.",
            "🔄 Reemplazar sensor si muestra daños irreversibles.",
            "📊 Comparar datos con estaciones cercanas para validación.",
            "🛠️ Programar mantenimiento correctivo inmediato."
        ]
    elif estado == 'riesgo':
        return [
            "🧽 Realizar limpieza y mantenimiento preventivo.",
            "📡 Verificar calibración y conectividad.",
            "📉 Analizar eventos recientes de lluvia para descartar fallos.",
            "🔍 Monitorear variaciones bruscas de datos.",
            "🔄 Considerar actualización de firmware."
        ]
    elif estado == 'ok':
        return [
            "✅ Continuar con mantenimiento preventivo cada 3-6 meses.",
            "📂 Realizar respaldo regular de datos.",
            "📝 Mantener bitácora de eventos y mantenimientos.",
            "🧑‍🏫 Capacitar al personal para conservación y análisis.",
            "🛰️ Revisar conectividad y batería periódicamente."
        ]
    return []

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
            # fechas_mantenimiento_predictivas = predecir_faltantes(serie, umbral=0.01) # Descomentar si usas Prophet
            anomalias = detectar_anomalias_y_tendencias(df, estacion)
            estado = 'ok'
            if porcentaje > 30 and datos_faltantes > 0: # Añadido datos_faltantes > 0 para evitar crítico con 0 faltantes
                estado = 'critico'
            elif porcentaje > 20 or len(anomalias) > 0:
                estado = 'riesgo'

            resultados[estacion] = {
                'total': total,
                'faltantes': datos_faltantes,
                'porcentaje': porcentaje,
                'fechas_faltantes': fechas_faltantes,
                # 'fechas_mantenimiento': fechas_mantenimiento_predictivas, # Descomentar si usas Prophet
                'fechas_anomalias': anomalias,
                'estado': estado,
                'alerta': estado in ['riesgo', 'critico'],
                'reporte_mensual': generar_reporte_mensual(df, estacion).to_dict(orient='records'),
                'recomendaciones': generar_recomendaciones(estado)
            }
        else:
            print(f"Advertencia: La columna '{estacion}' no se encontró en el archivo Excel.")
    return resultados, None

# --- Funciones de clima_app.py original (Datos Climáticos) ---

LAT = -0.481
LON = -78.141
TIMEZONE = 'America/Guayaquil'

def consultar_clima(fecha, lat=LAT, lon=LON):
    """
    Consulta datos climáticos históricos para una fecha y coordenadas dadas
    usando la API de Open-Meteo.
    """
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
        r.raise_for_status() # Lanza una excepción para códigos de estado HTTP de error
        data = r.json()
        # Asegurarse de que los datos diarios existan y contengan los valores esperados
        if 'daily' in data and data['daily'] and 'precipitation_sum' in data['daily'] and \
           'windspeed_10m_max' in data['daily'] and 'temperature_2m_max' in data['daily']:
            return {
                "precipitacion_mm": data['daily']['precipitation_sum'][0],
                "viento_max_kmh": data['daily']['windspeed_10m_max'][0],
                "temperatura_max": data['daily']['temperature_2m_max'][0]
            }
        else:
            print(f"Advertencia: Datos incompletos para {fecha_str}. API Response: {data}")
            return {
                "precipitacion_mm": None,
                "viento_max_kmh": None,
                "temperatura_max": None
            }
    except requests.exceptions.RequestException as e:
        print(f"Error de red o HTTP al consultar clima para {fecha_str}: {e}")
        return {
            "precipitacion_mm": None,
            "viento_max_kmh": None,
            "temperatura_max": None
        }
    except Exception as e:
        print(f"Error inesperado al consultar clima para {fecha_str}: {e}")
        return {
            "precipitacion_mm": None,
            "viento_max_kmh": None,
            "temperatura_max": None
        }

# --- Variable global para almacenar los datos climáticos para el bot ---
global_climate_data_df = None # Esta declaración inicial fuera de cualquier función está bien
# Variable global para almacenar los resultados del análisis de sensores
global_sensor_analysis_results = {}

# --- Rutas de la Aplicación ---

@app.route('/', methods=['GET', 'POST'])
def index():
    """
    Ruta principal para la carga de archivos Excel y visualización de mantenimiento de sensores.
    """
    global global_sensor_analysis_results # Declarar global para poder asignar
    resultados = {}
    error = None
    if request.method == 'POST':
        file = request.files.get('file')
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            resultados, error = analizar_excel(filepath)
            global_sensor_analysis_results = resultados # Almacenar resultados del análisis de sensores
        else:
            error = "Tipo de archivo no permitido o ningún archivo seleccionado."
    return render_template('index.html', resultados=resultados, error=error)

@app.route('/datos-climaticos')
def datos_climaticos_page():
    # ¡CORRECCIÓN AQUÍ! Mueve la declaración 'global' al principio de la función.
    global global_climate_data_df 

    # La ruta del archivo Excel ahora es relativa al directorio raíz de la aplicación
    # y se espera que esté en la carpeta 'data/' dentro del repositorio.
    excel_path = 'data/Precipitacion_Mensual__P42_P43_P5522062025222139.xlsx'

    if not os.path.exists(excel_path):
        print(f"Error: Archivo Excel no encontrado en {excel_path}")
        return "Error: El archivo Excel de precipitaciones no se encontró en el servidor. Asegúrate de que esté en la carpeta 'data/'.", 500

    try:
        df = pd.read_excel(excel_path)
        df['Fecha'] = pd.to_datetime(df['Fecha'], dayfirst=True)
    except Exception as e:
        print(f"Error al leer el archivo Excel para datos climáticos: {e}")
        return "Error al procesar el archivo Excel para datos climáticos. Asegúrate de que sea un formato válido.", 500

    sensores = ['P42', 'P43', 'P55']
    fechas_faltantes = []

    for sensor in sensores:
        if sensor in df.columns:
            faltantes = df[df[sensor].isna()][['Fecha']].copy()
            faltantes['Sensor'] = sensor
            fechas_faltantes.append(faltantes)
        else:
            print(f"Advertencia: El sensor '{sensor}' no se encontró en las columnas del Excel.")

    if not fechas_faltantes:
        # Aquí también asignamos, por lo que la declaración 'global' debe estar antes.
        global_climate_data_df = pd.DataFrame(columns=['Fecha', 'Sensor', 'precipitacion_mm', 'viento_max_kmh', 'temperatura_max'])
        return render_template('resultado.html', datos=[])
    
    faltantes_total = pd.concat(fechas_faltantes).reset_index(drop=True)

    climas = []
    print(f"Consultando clima para {len(faltantes_total)} fechas con datos faltantes...")
    for _, row in tqdm(faltantes_total.iterrows(), total=len(faltantes_total), desc="Consultando clima"):
        clima = consultar_clima(row['Fecha'])
        clima['Fecha'] = row['Sensor'] # Corregido: row['Fecha'] -> row['Sensor']
        clima['Sensor'] = row['Sensor'] # Corregido: row['Sensor'] -> row['Sensor']
        climas.append(clima)

    df_clima = pd.DataFrame(climas)
    # Usar 'left' merge para mantener todas las fechas faltantes, incluso si no se encontró clima
    resultado = pd.merge(faltantes_total, df_clima, on=['Fecha', 'Sensor'], how='left')

    # Almacenar el DataFrame en la variable global para que el bot pueda acceder a él
    # Esta asignación ahora es válida porque 'global' se declaró al inicio de la función.
    global_climate_data_df = resultado.copy() 

    # Guardar archivo Excel con dos hojas: original y completados (temporalmente en Render)
    output_excel_path = os.path.join(app.config['UPLOAD_FOLDER'], 'faltantes_resultado.xlsx')
    try:
        with pd.ExcelWriter(output_excel_path, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name='Original', index=False)
            resultado.to_excel(writer, sheet_name='Completados', index=False)
        print(f"Archivo 'faltantes_resultado.xlsx' guardado temporalmente en {output_excel_path}")
    except Exception as e:
        print(f"Error al guardar el archivo Excel de resultados: {e}")
        # La aplicación puede continuar, pero la descarga podría fallar si el archivo no se guarda.

    datos = resultado.to_dict(orient='records')
    return render_template('resultado.html', datos=datos)

@app.route('/descargar_faltantes')
def descargar_faltantes():
    """
    Permite la descarga del archivo Excel generado con los datos faltantes y completados.
    """
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], 'faltantes_resultado.xlsx')
    if os.path.exists(file_path):
        return send_file(file_path, as_attachment=True, download_name="faltantes_clima.xlsx")
    else:
        return 'Archivo no encontrado. Por favor, genera el reporte primero.', 404

@app.route('/ask-clima-bot', methods=['POST'])
def ask_clima_bot():
    """
    Endpoint para que el bot de clima responda preguntas basadas en los datos cargados.
    """
    user_query = request.json.get('query')
    if not user_query:
        return jsonify({"response": "Por favor, ingresa una pregunta."}), 400

    # Acceder a los datos climáticos y de análisis de sensores almacenados globalmente
    global global_climate_data_df
    global global_sensor_analysis_results

    # Definir la hipótesis del proyecto
    project_hypothesis = "El desarrollo e implementación de un sistema unificado para el monitoreo de sensores y la integración de datos climáticos reducirá el tiempo de detección de anomalías y datos faltantes en los sensores, y mejorará la capacidad de los usuarios para tomar decisiones informadas sobre el mantenimiento preventivo y correctivo, al proporcionar un acceso rápido y contextualizado a la información climática relevante."

    # Preparar el contexto de los datos para el LLM
    resumen_generado_por_sistema_parts = []

    # 1. Contexto de la hipótesis del proyecto
    resumen_generado_por_sistema_parts.append(f"Contexto del Proyecto (Hipótesis General): {project_hypothesis}")

    # 2. Contexto de los datos climáticos (si están disponibles)
    if global_climate_data_df is not None and not global_climate_data_df.empty:
        data_string_clima = global_climate_data_df.to_string(index=False, max_rows=50, max_colwidth=50)
        resumen_generado_por_sistema_parts.append(f"Datos climáticos históricos disponibles (Fechas sin datos con clima registrado):\n{data_string_clima}")
    else:
        resumen_generado_por_sistema_parts.append("No hay datos climáticos históricos cargados para consultar.")

    # 3. Contexto de los resultados del análisis de sensores (si están disponibles)
    if global_sensor_analysis_results:
        sensor_details_list = []
        for estacion, data in global_sensor_analysis_results.items():
            anomalies_info = f"Anomalías detectadas: {len(data['fechas_anomalias'])}."
            if data['fechas_anomalias']:
                # Proporcionar un sample de anomalías para concisión
                anomalies_sample = data['fechas_anomalias'][:3]
                anomalies_info += f" Ejemplos: {', '.join([f'{a["Fecha_str"]} (Var: {a["variacion"]:.2f}%)' for a in anomalies_sample])}"
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

    # Construir el prompt para el LLM con la nueva persona y capacidades
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

    # Obtener la clave API de Gemini desde las variables de entorno (Render)
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        print("Error: La clave API de Gemini (GEMINI_API_KEY) no está configurada en el servidor.")
        return jsonify({"response": "Error interno: La clave API del bot no está configurada."}), 500

    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2, # Baja temperatura para respuestas más fácticas
            "maxOutputTokens": 800 # Aumentado para permitir respuestas más detalladas y formales
        }
    }
    
    try:
        response = requests.post(api_url, headers={'Content-Type': 'application/json'}, json=payload)
        response.raise_for_status() # Lanza una excepción para errores HTTP (4xx o 5xx)
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


import os

port = int(os.environ.get("PORT", 5000))
app.run(host="0.0.0.0", port=port, debug=True)



