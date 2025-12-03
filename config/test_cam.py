import cv2

print("Buscando cámaras...")
for i in range(5):
    cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
    if cap.isOpened():
        ret, frame = cap.read()
        if ret:
            print(f"✅ Cámara encontrada en índice {i}: Resolución {frame.shape[1]}x{frame.shape[0]}")
            cv2.imshow(f'Camara {i}', frame)
        cap.release()

print("Presiona cualquier tecla en las ventanas para cerrar...")
cv2.waitKey(0)
cv2.destroyAllWindows()
