import os
import pandas as pd
from flask import Flask, render_template, request
from werkzeug.utils import secure_filename
from datetime import timedelta, datetime
from prophet import Prophet

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

ALLOWED_EXTENSIONS = {'xlsx'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def preparar_serie_faltantes(df, estacion):
    df_tmp = df[['Fecha', estacion]].copy()
    df_tmp['faltante'] = df_tmp[estacion].isna().astype(int)
    df_tmp['mes'] = df_tmp['Fecha'].dt.to_period('M').dt.to_timestamp()
    total_por_mes = df_tmp.groupby('mes').size()
    faltantes_por_mes = df_tmp.groupby('mes')['faltante'].sum()
    proporcion = (faltantes_por_mes / total_por_mes).reset_index()
    proporcion.columns = ['ds', 'y']
    return proporcion


#def predecir_faltantes(serie, umbral=0.01, meses_a_predecir=12)
   # if len(serie) < 3:
       # return []
   # model = Prophet(yearly_seasonality=True, weekly_seasonality=False, daily_seasonality=False)
   # model.fit(serie)
    #future = model.make_future_dataframe(periods=meses_a_predecir, freq='M')
    #forecast = model.predict(future)
    #hoy = pd.to_datetime(datetime.today().date())
    #predicciones_futuras = forecast[forecast['ds'] > hoy]
    #fechas_alerta = predicciones_futuras[predicciones_futuras['yhat'] > umbral]['ds'].dt.strftime('%Y-%m-%d').tolist()
    #return fechas_alerta

def detectar_anomalias_y_tendencias(df, estacion, umbral_porcentaje=50):
    df_tmp = df[['Fecha', estacion]].dropna().copy()
    df_tmp.sort_values('Fecha', inplace=True)
    df_tmp['variacion'] = df_tmp[estacion].pct_change() * 100
    df_tmp['tipo'] = df_tmp['variacion'].apply(lambda x: 'anomalía' if abs(x) > umbral_porcentaje else 'normal')
    df_tmp['Fecha_str'] = df_tmp['Fecha'].dt.strftime('%Y-%m-%d')
    anomalias = df_tmp[df_tmp['tipo'] == 'anomalía'][['Fecha_str', 'variacion']].to_dict(orient='records')
    return anomalias


def generar_reporte_mensual(df, estacion):
    df_tmp = df[['Fecha', estacion]].copy()
    df_tmp['mes'] = df_tmp['Fecha'].dt.to_period('M').dt.to_timestamp()
    resumen = df_tmp.groupby('mes').agg(total=('Fecha', 'count'),
                                        faltantes=(estacion, lambda x: x.isna().sum()),
                                        promedio=(estacion, 'mean')).reset_index()
    resumen['porcentaje_faltantes'] = (resumen['faltantes'] / resumen['total']) * 100
    return resumen

def generar_recomendaciones(estado):
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


# Agrega al análisis principal:
def analizar_excel(filepath):
    df = pd.read_excel(filepath, engine='openpyxl')
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
            #fechas_mantenimiento_predictivas = predecir_faltantes(serie, umbral=0.01)
            anomalias = detectar_anomalias_y_tendencias(df, estacion)
            estado = 'ok'
            if porcentaje > 30  > 0:
                estado = 'critico'
            elif porcentaje > 20 or len(anomalias) > 0:
                estado = 'riesgo'

           # if porcentaje > 30 and len(fechas_mantenimiento_predictivas) == 0:
            #    fechas_mantenimiento_predictivas = [(datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d')]

            resultados[estacion] = {
                'total': total,
                'faltantes': datos_faltantes,
                'porcentaje': porcentaje,
                'fechas_faltantes': fechas_faltantes,
                #'fechas_mantenimiento': fechas_mantenimiento_predictivas,
                'fechas_anomalias': anomalias,
                'estado': estado,
                'alerta': estado in ['riesgo', 'critico'],
                'reporte_mensual': generar_reporte_mensual(df, estacion).to_dict(orient='records'),
                'recomendaciones': generar_recomendaciones(estado)
            }
    return resultados


@app.route('/', methods=['GET', 'POST'])
def index():
    resultados = {}
    error = None
    if request.method == 'POST':
        file = request.files.get('file')
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            resultados = analizar_excel(filepath)
    return render_template('index.html', resultados=resultados, error=error)

@app.route('/analizar_web', methods=['POST'])
def analizar_web():
    resultados = {}
    error = None
    if request.method == 'POST':
        file = request.files.get('file')
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            resultados = analizar_excel(filepath)
    return render_template('index.html', resultados=resultados, error=error)

if __name__ == '__main__':
    os.makedirs('uploads', exist_ok=True)
    app.run(debug=True)