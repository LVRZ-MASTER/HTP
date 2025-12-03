import cv2
from threading import Thread
import time

class CameraStream:
    def __init__(self, src=0, width=1920, height=1080):
        """
        Clase para captura de video optimizada para Capturadoras HDMI (USB).
        Usa MJPG para minimizar latencia.
        """
        # Inicializar OpenCV con DirectShow (Windows) para evitar pantalla negra
        self.stream = cv2.VideoCapture(src, cv2.CAP_DSHOW)

        # Configuración crítica para Capturadoras HDMI USB
        # MJPG permite 1080p a 30/60fps sin comprimir el ancho de banda USB 2.0
        self.stream.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('M','J','P','G'))
        self.stream.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.stream.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.stream.set(cv2.CAP_PROP_BUFFERSIZE, 1) # Buffer mínimo para 'tiempo real'

        # Leer primer frame para verificar conexión
        (self.grabbed, self.frame) = self.stream.read()
        self.stopped = False

        if not self.grabbed:
            print(f"[ERROR CAMARA] No se pudo conectar al dispositivo {src}. Verifica cables HDMI.")

    def start(self):
        # Iniciar hilo en segundo plano para lectura continua
        Thread(target=self.update, args=(), daemon=True).start()
        return self

    def update(self):
        while not self.stopped:
            (grabbed, frame) = self.stream.read()
            if grabbed:
                self.frame = frame
            else:
                # Pequeña pausa si perdemos señal para no saturar CPU
                time.sleep(0.1)

    def read(self):
        # Devuelve el último frame disponible
        return self.frame

    def stop(self):
        self.stopped = True
        if self.stream.isOpened():
            self.stream.release()

# --- BLOQUE DE PRUEBA INDEPENDIENTE ---
if __name__ == "__main__":
    print("--- TEST CAPTURADORA HDMI ---")
    print("Presiona 'q' para salir.")

    # Intenta iniciar la cámara (usualmente índice 0 o 1)
    cam = CameraStream(src=0, width=1920, height=1080).start()

    while True:
        frame = cam.read()
        if frame is not None:
            # Reducimos tamaño solo para mostrar en pantalla (el bot usará 1080p real)
            preview = cv2.resize(frame, (960, 540))
            cv2.imshow("Vista Previa Capturadora", preview)
        else:
            print("Esperando señal de video...")
            time.sleep(1)

        if cv2.waitKey(1) == ord('q'):
            break

    cam.stop()
    cv2.destroyAllWindows()
