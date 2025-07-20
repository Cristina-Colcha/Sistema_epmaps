import subprocess

if __name__ == '__main__':
    # Ejecuta app.py en un proceso separado
    p1 = subprocess.Popen(['python', 'app.py'])

    # Ejecuta faltantes.py en otro proceso
    p2 = subprocess.Popen(['python', 'faltantes.py'])

    # Espera a que ambos procesos terminen
    p1.wait()
    p2.wait()
