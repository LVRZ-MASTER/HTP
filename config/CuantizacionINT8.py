from ultralytics import YOLO

# 1. Definir rutas (Ajusta esto cuando tengas tu nuevo best.pt)
ruta_modelo_entrenado = "../runs/detect/train/weights/best.pt"

# 2. Cargar el modelo
print(f"🔄 Cargando modelo desde: {ruta_modelo_entrenado}")
model = YOLO(ruta_modelo_entrenado)

# 3. Exportar a OpenVINO con Cuantización (INT8)
# imgsz=640: El tamaño de tus fotos
# int8=True: La magia que lo hace rápido
# data=...: Necesario para calibrar la precisión del INT8 (usa tu data.yaml)
print("🚀 Iniciando exportación optimizada para CPU (esto puede tardar unos minutos)...")

model.export(
    format='openvino',
    imgsz=640,
    int8=True,
    data='../dataset_v2/data.yaml' # ¡Asegúrate de que apunte a tu yaml!
)

print("✅ ¡Listo! Se ha creado una carpeta 'best_openvino_model'")
