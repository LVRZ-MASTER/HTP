import asyncio
import json
import os
import socket
import threading
import time
from typing import Any, Dict

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn


class HTPGUIPlugin:
    """
    GUI web completa (FastAPI + WebSocket).
    Visualiza el estado del juego, decisiones y logs.
    v3.9: Soporte para formatos GGPoker (3-Max, 4-Max, 8-Max, etc.)
    """

    def __init__(self) -> None:
        self.app: FastAPI | None = None
        self.host: str = "0.0.0.0"
        self.port: int = 8000
        self._state_ref: Dict[str, Any] | None = None
        self._server_thread: threading.Thread | None = None
        self._server_start_error: str | None = None

        self.base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.html_path = os.path.join(self.base_dir, "interface.html")
        self.ico_path = os.path.join(self.base_dir, "icoRGB.ico")
        self.config_dir = os.path.join(self.base_dir, "config")

    def setup(self, state: Dict[str, Any], config: Dict[str, Any]) -> None:
        self._state_ref = state
        self.host = config.get("host", "0.0.0.0")
        try:
            self.port = int(config.get("port", 8000))
        except Exception:
            self.port = 8000

        debug = state.setdefault("debug", {})
        debug.setdefault("gui_last_error", "")
        debug.setdefault("gui_listening", False)

        app = FastAPI()
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

        if os.path.exists(self.base_dir):
            app.mount("/static", StaticFiles(directory=self.base_dir), name="static")

        @app.get("/", response_class=HTMLResponse)
        async def root():
            if os.path.exists(self.html_path):
                try:
                    with open(self.html_path, "r", encoding="utf-8") as f:
                        return f.read()
                except Exception:
                    pass
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
                "gui_listening": state.get("debug", {}).get("gui_listening", False),
            }

        @app.get("/state")
        async def full_state():
            return {
                "decision": state.get("decision", {}),
                "game_state": state.get("game_state", {}),
                "ocr_data": state.get("ocr_data", {}),
                "vision_ok": state.get("vision_ok", False),
                "errors": state.get("errors", [])[-50:],
                "fps_current": state.get("fps_current", 0.0),
                "window_title": state.get("window_title", ""),
                "debug": state.get("debug", {}),
            }

        @app.websocket("/ws")
        async def ws_endpoint(ws: WebSocket):
            await ws.accept()
            try:
                while True:
                    await asyncio.sleep(0.1)

                    payload = {
                        "decision": state.get("decision", {}),
                        "game_state": state.get("game_state", {}),
                        "vision_ok": state.get("vision_ok", False),
                        "errors": state.get("errors", [])[-20:],
                        "fps_current": state.get("fps_current", 0.0),
                        "window_title": state.get("window_title", ""),
                        "debug": state.get("debug", {}),
                    }
                    await ws.send_text(json.dumps(payload))
            except Exception:
                pass
            finally:
                try:
                    await ws.close()
                except Exception:
                    pass

        self.app = app

        if not self._server_thread or not self._server_thread.is_alive():
            self._server_thread = threading.Thread(target=self._run_uvicorn_server, daemon=True)
            self._server_thread.start()
            threading.Timer(2.0, self._check_startup).start()

    def _check_startup(self):
        if self._state_ref and not self._server_start_error:
             self._state_ref["debug"]["gui_listening"] = True

    def _run_uvicorn_server(self) -> None:
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            config = uvicorn.Config(self.app, host=self.host, port=self.port, log_level="critical")
            server = uvicorn.Server(config)
            server.run()
        except Exception as e:
            self._server_start_error = str(e)
            if self._state_ref:
                self._state_ref["debug"]["gui_last_error"] = f"GUI start fail: {e}"

    def _fallback_html(self) -> str:
        return """<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Centro de comando HTP</title>
    <style>
        :root {
            --bg-color: #121212;
            --panel-bg: #1e1e1e;
            --text-main: #e0e0e0;
            --text-muted: #888;
            --accent: #ff4444;
            --border: #333;
            --card-bg: #eee;
            --success: #00c851;
            --font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
        }

        body {
            background-color: var(--bg-color);
            color: var(--text-main);
            font-family: var(--font-family);
            margin: 0; padding: 0; height: 100vh;
            display: flex; flex-direction: column; overflow: hidden;
        }

        header {
            background: #000; border-bottom: 1px solid var(--accent);
            padding: 10px 20px; display: flex; justify-content: space-between;
            align-items: center; height: 50px;
        }

        .logo { font-weight: bold; font-size: 1.2rem; letter-spacing: 1px; color: #fff; }
        .logo span { color: var(--accent); }

        .header-stats { font-size: 0.9rem; color: var(--text-muted); display: flex; gap: 20px; }
        .stat-item { display: flex; align-items: center; gap: 5px; }
        .stat-item b { color: #fff; }
        .stat-item b.format { color: #4db8ff; text-shadow: 0 0 5px rgba(77, 184, 255, 0.5); }

        .status-dot {
            height: 10px; width: 10px; border-radius: 50%; display: inline-block;
            background: #555; margin-right: 5px; box-shadow: 0 0 5px #000;
        }
        .status-dot.ok { background: var(--success); box-shadow: 0 0 8px var(--success); }
        .status-dot.err { background: var(--accent); box-shadow: 0 0 8px var(--accent); }

        /* GRID LAYOUT */
        .dashboard-grid {
            display: grid; grid-template-columns: 300px 1fr 350px; gap: 2px;
            flex: 1; background: var(--border); overflow: hidden;
        }

        .panel { background: var(--panel-bg); padding: 20px; overflow-y: auto; display: flex; flex-direction: column; }

        h2 { margin-top: 0; font-size: 1rem; text-transform: uppercase; letter-spacing: 1px; color: var(--text-muted); border-bottom: 1px solid var(--border); padding-bottom: 10px; margin-bottom: 15px; }

        h1.action-display {
            font-size: 2.0rem;
            text-align: center;
            margin: 10px 0;
            color: #fff;
            text-shadow: 0 0 10px rgba(255,255,255,0.1);
            line-height: 1.2;
            word-wrap: break-word;
        }

        .decision-box {
            background: rgba(255,255,255,0.05); border-radius: 8px; padding: 15px;
            text-align: center; border: 1px solid var(--border); margin-bottom: 15px;
            overflow: hidden;
        }

        .equity-val {
            font-size: 2.5rem;
            font-weight: bold;
            color: var(--success);
            line-height: 1.1;
        }

        .label { font-size: 0.8rem; text-transform: uppercase; color: var(--text-muted); margin-bottom: 5px; display: block; }

        .tags-container { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; margin-top: 5px; }
        .tag {
            background: #333; color: #ddd; padding: 4px 10px; border-radius: 15px;
            font-size: 0.8rem; border: 1px solid #444; font-weight: 600;
        }
        .tag.special { border-color: var(--accent); color: #fff; background: #3a1111; }

        /* TABLE VISUAL */
        .table-visual {
            flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center;
            background: radial-gradient(circle at center, #2a2a2a 0%, #1a1a1a 100%);
        }
        .cards-container { display: flex; gap: 10px; justify-content: center; margin-bottom: 20px; flex-wrap: wrap;}

        .opponents-wrapper {
            display: flex; gap: 20px; justify-content: center; flex-wrap: wrap;
            margin-bottom: 20px; width: 100%;
        }
        .opponent-hand {
            background: rgba(255,255,255,0.05);
            padding: 5px 10px;
            border-radius: 8px;
            display: flex;
            gap: 5px;
            border: 1px solid #444;
        }

        .card {
            width: 45px; height: 65px; background: var(--card-bg); border-radius: 4px;
            color: #000; font-weight: bold; font-size: 1.1rem; display: flex; flex-direction: column;
            align-items: center; justify-content: center; box-shadow: 0 2px 10px rgba(0,0,0,0.5);
            position: relative; user-select: none;
        }
        .card.small { width: 30px; height: 45px; font-size: 0.8rem; }
        .card.red { color: #d00; }
        .card.black { color: #000; }

        /* ESTILO PARA CARD BACK */
        .card.back {
            background: repeating-linear-gradient(
                45deg,
                #606dbc,
                #606dbc 5px,
                #465298 5px,
                #465298 10px
            );
            border: 1px solid #fff;
            color: transparent;
        }

        .card span { font-size: 1.2rem; line-height: 1; }
        .card.small span { font-size: 0.9rem; }

        .street-badge {
            background: #333; color: #fff; padding: 5px 15px; border-radius: 20px;
            font-size: 0.8rem; text-transform: uppercase; letter-spacing: 1px;
            margin-bottom: 20px; border: 1px solid #555;
        }

        /* LOGS */
        .log-console {
            background: #000; color: #0f0; font-family: 'Consolas', 'Monaco', monospace;
            font-size: 0.8rem; flex: 1; padding: 10px; border: 1px solid #333; overflow-y: auto;
            white-space: pre-wrap;
        }
        .debug-row { display: flex; justify-content: space-between; border-bottom: 1px solid #333; padding: 8px 0; font-size: 0.85rem; }
        .debug-val { font-family: monospace; color: #fff; }

    </style>
</head>
<body>

    <header>
        <div class="logo">Centro de comando HTP</div>
        <div class="header-stats">
            <div class="stat-item">Formato: <b id="table-format" class="format">Detectando...</b></div>
            <div class="stat-item">Jugando: <b id="active-players">--</b></div>
            <div class="stat-item"><span id="vision-dot" class="status-dot"></span> <span id="vision-text">Visión</span></div>
            <div class="stat-item">FPS: <b id="fps">0</b></div>
        </div>
    </header>

    <div class="dashboard-grid">
        <!-- LEFT -->
        <div class="panel">
            <h2>Estrategia</h2>
            <div class="decision-box">
                <span class="label">Acción</span>
                <h1 id="action" class="action-display">ESPERAR</h1>
            </div>
            <div class="decision-box">
                <span class="label">Equity</span>
                <div id="equity" class="equity-val">--%</div>
            </div>
            <div class="decision-box">
                <span class="label">Contexto & Rival</span>
                <div id="tags-box" class="tags-container">
                    <span class="tag" style="opacity:0.5">--</span>
                </div>
            </div>
            <div class="debug-row"><span>Pot Odds</span> <span id="pot_odds" class="debug-val">--</span></div>
        </div>

        <!-- CENTER -->
        <div class="panel table-visual">
            <span class="label">Rivales Detectados</span>
            <div id="opponents-wrapper" class="opponents-wrapper">
                <div style="color:#555; font-style:italic;">--</div>
            </div>

            <div id="street" class="street-badge">PREFLOP</div>

            <span class="label">Board</span>
            <div id="board-container" class="cards-container"><div style="color:#555">--</div></div>

            <div style="height: 40px;"></div>

            <span class="label">Hero</span>
            <div id="hero-container" class="cards-container"><div style="color:#555">-- --</div></div>
        </div>

        <!-- RIGHT -->
        <div class="panel">
            <h2>Sistema</h2>
            <div style="margin-bottom: 15px;">
                <div class="debug-row"><span>Modelo</span> <span id="d-model" class="debug-val">--</span></div>
                <div class="debug-row"><span>Asientos Confirmados</span> <span id="d-seats" class="debug-val">0</span></div>
                <div class="debug-row"><span>OCR Status</span> <span id="d-ocr" class="debug-val" style="color:#f55;">--</span></div>
            </div>
            <h2>Logs</h2>
            <div id="log-box" class="log-console">Iniciando...</div>
        </div>
    </div>

    <script>
        const wsUrl = (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws';
        const logBox = document.getElementById('log-box');

        function cardToHTML(c, isSmall) {
             if(!c) return '';

             // --- CORRECCIÓN ESTÉTICA ---
             // Si detectamos card_back, dibujamos una carta boca abajo (clase .back)
             if (c === 'card_back') {
                 let extraClass = isSmall ? 'small' : '';
                 return `<div class="card back ${extraClass}"></div>`;
             }

             if(c.length < 2) return '';

             let rankRaw = c.substring(0, c.length - 1);
             let suit = c.substring(c.length - 1).toLowerCase();
             let rank = rankRaw;
             if (typeof rankRaw === 'string') {
                 rankRaw = rankRaw.trim();
                 if (rankRaw.toUpperCase() === 'T') rank = '10';
                 else rank = rankRaw;
             }
             let suitChar = '';
             let colorClass = 'black';
             if (suit === 'h') { suitChar = '♥'; colorClass = 'red'; }
             else if (suit === 'd') { suitChar = '♦'; colorClass = 'red'; }
             else if (suit === 'c') { suitChar = '♣'; colorClass = 'black'; }
             else if (suit === 's') { suitChar = '♠'; colorClass = 'black'; }

             let extraClass = isSmall ? 'small' : '';
             return `<div class="card ${colorClass} ${extraClass}">${rank}<span>${suitChar}</span></div>`;
        }

        function renderSimpleList(containerId, cardsList) {
            const container = document.getElementById(containerId);
            if (!cardsList || cardsList.length === 0) {
                container.innerHTML = '<div style="color:#444; font-style:italic;">--</div>';
                return;
            }
            let html = '';
            cardsList.forEach(c => html += cardToHTML(c, false));
            container.innerHTML = html;
        }

        function renderOpponentsGroups(groups) {
            const container = document.getElementById('opponents-wrapper');
            if (!groups || groups.length === 0) {
                container.innerHTML = '<div style="color:#444; font-style:italic;">--</div>';
                return;
            }
            let html = '';
            groups.forEach(grp => {
                if (!grp || grp.length === 0) return;
                html += '<div class="opponent-hand">';
                grp.forEach(c => {
                    html += cardToHTML(c, true);
                });
                html += '</div>';
            });
            container.innerHTML = html;
        }

        function inferTableFormat(seats) {
            if (seats <= 2) return "Heads Up (2)";
            if (seats === 3) return "Spin & Gold (3-Max)";
            if (seats === 4) return "AoF (4-Max)";
            if (seats === 5) return "Short Deck (5-Max)";
            if (seats === 6) return "Cash (6-Max)";
            if (seats === 8) return "MTT (8-Max)";
            if (seats === 9) return "Full Ring (9-Max)";
            return "Custom (" + seats + ")";
        }

        function connect() {
            const ws = new WebSocket(wsUrl);
            ws.onopen = () => { console.log('WS OK'); logBox.innerText = ">>> SISTEMA ONLINE\\n"; };
            ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);

                    document.getElementById('fps').textContent = parseFloat(data.fps_current || 0).toFixed(1);

                    const vDot = document.getElementById('vision-dot');
                    const vText = document.getElementById('vision-text');
                    if(data.vision_ok) { vDot.className = 'status-dot ok'; vText.textContent = 'OK'; }
                    else { vDot.className = 'status-dot err'; vText.textContent = 'FAIL'; }

                    const dec = data.decision || {};
                    const act = document.getElementById('action');
                    act.textContent = dec.action || 'ESPERAR';
                    act.style.color = (dec.action === 'FOLD') ? '#ff4444' : (dec.action && dec.action.includes('RAISE') ? '#00c851' : '#fff');

                    document.getElementById('equity').textContent = dec.equity || '--%';
                    document.getElementById('pot_odds').textContent = dec.pot_odds || '--';

                    const tagsBox = document.getElementById('tags-box');
                    const tags = dec.tags || [];
                    if (tags.length > 0) {
                        tagsBox.innerHTML = tags.map(t => {
                            const isSpecial = t === 'DURISIMO' || t.startsWith('Req:');
                            return `<span class="tag ${isSpecial ? 'special' : ''}">${t}</span>`;
                        }).join('');
                    } else {
                        tagsBox.innerHTML = '<span class="tag" style="opacity:0.5">--</span>';
                    }

                    const game = data.game_state || {};
                    const dbg = data.debug || {};

                    // --- CORRECCIÓN LOGICA: "JUGANDO" ---
                    const active = game.active_players || 0;       // Tamaño mesa
                    const inHand = game.players_in_hand || 0;      // Cartas vivas

                    // Mostramos: "Jugando: 3 / 6" (Vivos / Totales)
                    document.getElementById('active-players').textContent = `${inHand} / ${active}`;

                    const totalSeats = dbg.total_seats_tracked || active;
                    const formatText = inferTableFormat(totalSeats);
                    document.getElementById('table-format').textContent = formatText;

                    document.getElementById('street').textContent = game.street || 'PREFLOP';
                    const myCards = (game.my_cards && game.my_cards.length) ? game.my_cards : (dbg.last_my_cards || []);
                    const boardCards = (game.board && game.board.length) ? game.board : (dbg.last_board_cards || []);

                    let oppCards = game.opponents_cards || [];
                    if (oppCards.length === 0 && dbg.last_opponents_cards && dbg.last_opponents_cards.length > 0) {
                        oppCards = [dbg.last_opponents_cards];
                    }

                    renderSimpleList('hero-container', myCards);
                    renderSimpleList('board-container', boardCards);
                    renderOpponentsGroups(oppCards);

                    document.getElementById('d-model').textContent = dbg.vision_core_loaded ? "ON" : "OFF";
                    document.getElementById('d-seats').textContent = totalSeats;
                    document.getElementById('d-ocr').textContent = (dbg.ocr_last_error || "OK").substring(0,15);

                    if (data.errors && data.errors.length > 0) {
                        const txt = data.errors.join('\\n');
                        if (logBox.textContent !== txt) {
                             logBox.textContent = txt;
                             logBox.scrollTop = logBox.scrollHeight;
                        }
                    }

                } catch (e) { console.error(e); }
            };

            ws.onclose = () => { logBox.innerText += ">>> CONEXIÓN PERDIDA. Reintentando...\\n"; setTimeout(connect, 2000); };
        }

        connect();
    </script>
</body>
</html>
"""
