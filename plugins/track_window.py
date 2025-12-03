import cv2
import pygetwindow as gw
import time
import sys
import os

# --- INTEGRACIÓN ---
# Importamos la clase CameraStream desde el archivo camera.py
# Esto permite que si mejoras la cámara, todos los plugins se actualicen solos.
try:
    from .camera import CameraStream
except ImportError:
    # Fallback por si ejecutamos este archivo directo desde la carpeta plugins/
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    from camera import CameraStream

class WindowTracker:
    def __init__(self, window_name_pattern):
        self.window_name_pattern = window_name_pattern
        self.target_window = None
        self.update_window_reference()

    def update_window_reference(self):
        """Busca la ventana nuevamente si se perdió o al inicio"""
        ventanas = gw.getWindowsWithTitle(self.window_name_pattern)
        if ventanas:
            # Tomamos la primera coincidencia
            self.target_window = ventanas[0]
            return True
        return False

    def get_crop_coords(self):
        """Devuelve (x, y, w, h) seguros para recortar el frame"""
        if not self.target_window:
            if not self.update_window_reference():
                return None

        try:
            # Obtenemos geometría actual de la ventana
            # NOTA: pygetwindow puede dar valores raros si la ventana está minimizada
            if self.target_window.isMinimized:
                return None

            x, y, w, h = self.target_window.left, self.target_window.top, self.target_window.width, self.target_window.height

            # Limpieza de coordenadas (evitar negativos que crashean OpenCV)
            x = max(0, x)
            y = max(0, y)
            # Asegurarnos de que w y h sean positivos
            w = max(1, w)
            h = max(1, h)

            return (x, y, w, h)
        except Exception as e:
            # Si la ventana se cerró, intentamos buscarla de nuevo
            print(f"[WARN] Error leyendo ventana: {e}")
            self.target_window = None
            return None

# --- BLOQUE DE PRUEBA ---
if __name__ == "__main__":
    # NOMBRE DE LA VENTANA A SEGUIR (Cámbialo por el de tu Poker)
    TARGET_NAME = "Bloc de notas"

    print(f"[INFO] Buscando ventana que contenga: '{TARGET_NAME}'...")
    tracker = WindowTracker(TARGET_NAME)

    # Iniciamos la cámara (Importada de camera.py)
    cam = CameraStream(src=0, width=1920, height=1080).start()
    time.sleep(1.0)

    print("[INFO] Sistema de Auto-Tracking iniciado. Mueve la ventana para probar.")
    print("Presiona 'q' para salir.")

    while True:
        frame = cam.read()

        if frame is not None:
            coords = tracker.get_crop_coords()

            if coords:
                x, y, w, h = coords

                # PROTECCIÓN DE LÍMITES
                # Si la ventana se sale de la resolución de la cámara (1920x1080), recortamos el crop
                h_img, w_img = frame.shape[:2]
                if x + w > w_img: w = w_img - x
                if y + h > h_img: h = h_img - y

                # CROP DINÁMICO
                roi = frame[y:y+h, x:x+w]

                if roi.size > 0:
                    cv2.imshow("PokerZ - Auto Tracking", roi)
                else:
                    print("[WARN] ROI vacío (ventana fuera de pantalla?)")
            else:
                # Si no encuentra la ventana, mostramos todo y avisamos
                # cv2.putText(frame, "BUSCANDO VENTANA...", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
                cv2.imshow("HTP - Auto Tracking", frame)

        if cv2.waitKey(1) == ord("q"):
            break

    cam.stop()
    cv2.destroyAllWindows()
