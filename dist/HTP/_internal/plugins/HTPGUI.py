import json
import os
from typing import Any, Dict

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn


class HTPGUIPlugin:
    """
    Plugin de interfaz (FastAPI + WebSocket + estáticos).

    Responsabilidades:
    - Levantar un servidor FastAPI embebido en el mismo proceso.
    - Servir:
        - /              -> interface.html (si existe) o HTML de fallback.
        - /favicon.ico   -> icoRGB.ico (si existe).
        - /static/*      -> interface.css, icoRGB.ico y otros estáticos.
    - Exponer:
        - /status        -> estado mínimo (running, vision_ok).
        - /state         -> estado resumido para depuración.
        - /ws            -> WebSocket con estado en tiempo real.
    """

    def __init__(self) -> None:
        self.app: FastAPI | None = None
        self.host: str = "0.0.0.0"
        self.port: int = 8000
        self._state_ref: Dict[str, Any] | None = None
        self._server_started: bool = False

        # BASE_DIR es la carpeta raíz del proyecto (donde está htp.py, interface.html, etc.)
        self.base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.html_path = os.path.join(self.base_dir, "interface.html")
        self.css_path = os.path.join(self.base_dir, "interface.css")
        self.ico_path = os.path.join(self.base_dir, "icoRGB.ico")

    def setup(self, state: Dict[str, Any], config: Dict[str, Any]) -> None:
        self._state_ref = state
        self.host = config.get("host", "0.0.0.0")
        self.port = int(config.get("port", 8000))

        app = FastAPI()
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # Montar estáticos si existen interface.css o icoRGB.ico
        if os.path.exists(self.css_path) or os.path.exists(self.ico_path):
            static_dir = self.base_dir
            app.mount("/static", StaticFiles(directory=static_dir), name="static")

        @app.get("/", response_class=HTMLResponse)
        async def root():
            # Si existe interface.html física, servirla
            if os.path.exists(self.html_path):
                try:
                    with open(self.html_path, "r", encoding="utf-8") as f:
                        return f.read()
                except Exception:
                    # Si hay problema leyendo el archivo, caemos al fallback
                    return self._fallback_html()
            # Fallback: HTML mínimo embebido
            return self._fallback_html()

        @app.get("/favicon.ico")
        async def favicon():
            if os.path.exists(self.ico_path):
                return FileResponse(self.ico_path, media_type="image/x-icon")
            return HTMLResponse(status_code=404, content="")

        @app.get("/status")
        async def status():
            return {
                "running": state.get("running", True),
                "vision_ok": state.get("vision_ok", False),
            }

        @app.get("/state")
        async def full_state():
            return {
                "decision": state.get("decision", {}),
                "game_state": state.get("game_state", {}),
                "ocr_data": state.get("ocr_data", {}),
                "vision_ok": state.get("vision_ok", False),
                "errors": state.get("errors", [])[-10:],
            }

        @app.websocket("/ws")
        async def ws_endpoint(ws: WebSocket):
            await ws.accept()
            try:
                while True:
                    # Recibir comandos simples (opcional)
                    try:
                        msg = await ws.receive_json()
                        action = msg.get("action")
                        if action == "ping":
                            await ws.send_json({"type": "pong"})
                        # Aquí se podrían manejar otros comandos si se define un canal
                    except Exception:
                        # Ignoramos errores de lectura; seguimos enviando estado
                        pass

                    payload = {
                        "decision": state.get("decision", {}),
                        "game_state": state.get("game_state", {}),
                        "ocr_data": state.get("ocr_data", {}),
                        "vision_ok": state.get("vision_ok", False),
                        "errors": state.get("errors", [])[-5:],
                    }
                    await ws.send_text(json.dumps(payload))
            except Exception:
                # Cliente desconectado.
                pass

        self.app = app

        if not self._server_started:
            import threading

            def _run_server():
                uvicorn.run(
                    self.app,
                    host=self.host,
                    port=self.port,
                    log_level="info",
                )

            t = threading.Thread(target=_run_server, daemon=True)
            t.start()
            self._server_started = True

    def _fallback_html(self) -> str:
        """
        HTML mínimo si no existe interface.html en disco.
        Usa /static/interface.css si está disponible.
        """
        return """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <title>HTP Dashboard</title>
  <link rel="icon" type="image/x-icon" href="/static/icoRGB.ico">
  <link rel="stylesheet" href="/static/interface.css">
  <style>
    /* Fallback rápido si no se carga interface.css */
    body { font-family: Arial, sans-serif; background-color: #111; color: #eee; }
    .container { max-width: 900px; margin: 20px auto; padding: 10px; }
    .card { background: #222; border-radius: 8px; padding: 12px; margin-bottom: 12px; }
    .title { font-size: 1.3rem; margin-bottom: 8px; }
    .value { font-size: 1.1rem; }
    .status-dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; margin-right: 6px; }
  </style>
</head>
<body>
  <div class="container">
    <div class="card">
      <div class="title">Estado Captura</div>
      <div class="value">
        <span id="vision-status-dot" class="status-dot" style="background:#777;"></span>
        <span id="vision-status-text">Desconocido</span>
      </div>
    </div>

    <div class="card">
      <div class="title">Decisión</div>
      <div class="value">
        Equity: <span id="equity">--%</span><br>
        Acción: <span id="action">ESPERANDO...</span><br>
        Pot Odds: <span id="pot_odds"></span><br>
        Tags: <span id="tags"></span>
      </div>
    </div>

    <div class="card">
      <div class="title">Game State</div>
      <div class="value">
        Street: <span id="street">PREFLOP</span><br>
        Mis Cartas: <span id="my_cards"></span><br>
        Board: <span id="board"></span><br>
        Blinds: <span id="blinds"></span>
      </div>
    </div>

    <div class="card">
      <div class="title">Errores recientes</div>
      <pre id="errors" style="white-space: pre-wrap; font-size: 0.9rem;"></pre>
    </div>
  </div>

  <script>
    const wsUrl = (location.protocol === 'https:' ? 'wss://' : 'ws://')
                + location.host + '/ws';

    function cardListToString(cards) {
      if (!cards || !cards.length) return '';
      return cards.join(' ');
    }

    function updateVision(ok) {
      const dot = document.getElementById('vision-status-dot');
      const text = document.getElementById('vision-status-text');
      if (ok) {
        dot.style.background = '#0f0';
        text.textContent = 'OK';
      } else {
        dot.style.background = '#f00';
        text.textContent = 'Problema de visión / pantalla negra';
      }
    }

    function connect() {
      const ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        console.log('WS conectado');
        ws.send(JSON.stringify({ action: 'ping' }));
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          const decision = data.decision || {};
          const game = data.game_state || {};
          const ocr = data.ocr_data || {};

          document.getElementById('equity').textContent = decision.equity || '--%';
          document.getElementById('action').textContent = decision.action || 'ESPERANDO...';
          document.getElementById('pot_odds').textContent = decision.pot_odds || '';
          document.getElementById('tags').textContent = (decision.tags || []).join(', ');

          document.getElementById('street').textContent = game.street || 'PREFLOP';
          document.getElementById('my_cards').textContent = cardListToString(game.my_cards || []);
          document.getElementById('board').textContent = cardListToString(game.board || []);
          const blinds = game.blinds || {};
          document.getElementById('blinds').textContent =
            `SB: ${blinds.sb || 0}, BB: ${blinds.bb || 0}`;

          updateVision(!!data.vision_ok);

          const errs = data.errors || [];
          document.getElementById('errors').textContent = errs.join('\\n');
        } catch (e) {
          console.error('Error parseando mensaje WS', e);
        }
      };

      ws.onclose = () => {
        console.log('WS cerrado, reintento en 2s...');
        setTimeout(connect, 2000);
      };

      ws.onerror = (err) => {
        console.error('WS error', err);
        ws.close();
      };
    }

    connect();
  </script>
</body>
</html>
"""

    def process(self, state: Dict[str, Any]) -> None:
        # La mayor parte del trabajo la hace FastAPI/uvicorn en otro hilo.
        return
