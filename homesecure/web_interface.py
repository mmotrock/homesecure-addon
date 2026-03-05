#!/usr/bin/env python3
"""
HomeSecure Add-on Web Interface
Provides management UI and log viewer accessible via ingress
"""
import asyncio
import json
import logging
from aiohttp import web
from pathlib import Path
import sqlite3

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('homesecure.web')

class HomeSecureWeb:
    """Web interface for HomeSecure add-on."""
    
    def __init__(self):
        self.app = web.Application()
        self.setup_routes()
        
    def setup_routes(self):
        """Setup web routes."""
        self.app.router.add_get('/', self.index)
        self.app.router.add_get('/logs', self.logs_page)
        self.app.router.add_get('/api/logs', self.api_logs)
        self.app.router.add_get('/api/status', self.api_status)
    
    async def index(self, request):
        """Main page."""
        html = """
<!DOCTYPE html>
<html>
<head>
    <title>HomeSecure Management</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f5f5f5;
            padding: 20px;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 12px;
            padding: 30px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }
        h1 {
            color: #333;
            margin-bottom: 10px;
            display: flex;
            align-items: center;
            gap: 12px;
        }
        .shield { font-size: 32px; }
        .subtitle { color: #666; margin-bottom: 30px; }
        .card {
            background: #f9f9f9;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 20px;
        }
        .card h2 {
            color: #444;
            margin-bottom: 15px;
            font-size: 18px;
        }
        .status {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 10px;
            background: white;
            border-radius: 6px;
            margin-bottom: 10px;
        }
        .status-dot {
            width: 12px;
            height: 12px;
            border-radius: 50%;
            background: #10b981;
        }
        .status-dot.warning { background: #f59e0b; }
        .status-dot.error { background: #ef4444; }
        .btn {
            background: #667eea;
            color: white;
            border: none;
            padding: 12px 24px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 500;
            text-decoration: none;
            display: inline-block;
            transition: all 0.2s;
        }
        .btn:hover {
            background: #5568d3;
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
        }
        .info-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 15px;
            margin-top: 15px;
        }
        .info-item {
            padding: 15px;
            background: white;
            border-radius: 6px;
            border-left: 3px solid #667eea;
        }
        .info-label {
            font-size: 12px;
            color: #666;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 5px;
        }
        .info-value {
            font-size: 18px;
            font-weight: 600;
            color: #333;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>
            <span class="shield">🛡️</span>
            HomeSecure Management
        </h1>
        <p class="subtitle">Add-on Version 1.0.0</p>
        
        <div class="card">
            <h2>System Status</h2>
            <div class="status">
                <div class="status-dot" id="status-integration"></div>
                <span>Integration: <strong id="integration-status">Loading...</strong></span>
            </div>
            <div class="status">
                <div class="status-dot" id="status-cards"></div>
                <span>Lovelace Cards: <strong id="cards-status">Loading...</strong></span>
            </div>
            <div class="status">
                <div class="status-dot" id="status-logs"></div>
                <span>Log Service: <strong id="logs-status">Running</strong></span>
            </div>
        </div>
        
        <div class="card">
            <h2>Quick Actions</h2>
            <div style="display: flex; gap: 10px; flex-wrap: wrap;">
                <a href="/logs" class="btn">📋 View Logs</a>
                <a href="#" class="btn" onclick="openHA(); return false;">⚙️ Configure Integration</a>
                <a href="#" class="btn" onclick="restartHA(); return false;">🔄 Restart Home Assistant</a>
            </div>
        </div>
        
        <div class="card">
            <h2>Information</h2>
            <div class="info-grid">
                <div class="info-item">
                    <div class="info-label">Integration Path</div>
                    <div class="info-value" style="font-size: 12px;">/config/custom_components/homesecure</div>
                </div>
                <div class="info-item">
                    <div class="info-label">Cards Path</div>
                    <div class="info-value" style="font-size: 12px;">/config/www/homesecure-*.js</div>
                </div>
                <div class="info-item">
                    <div class="info-label">Database</div>
                    <div class="info-value" style="font-size: 12px;">/config/homesecure.db</div>
                </div>
                <div class="info-item">
                    <div class="info-label">Logs</div>
                    <div class="info-value" style="font-size: 12px;">/var/log/homesecure/</div>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        async function checkStatus() {
            try {
                const response = await fetch('/api/status');
                const data = await response.json();
                
                // Update integration status
                const integrationDot = document.getElementById('status-integration');
                const integrationText = document.getElementById('integration-status');
                if (data.integration_installed) {
                    integrationDot.className = 'status-dot';
                    integrationText.textContent = 'Installed';
                } else {
                    integrationDot.className = 'status-dot error';
                    integrationText.textContent = 'Not Installed';
                }
                
                // Update cards status
                const cardsDot = document.getElementById('status-cards');
                const cardsText = document.getElementById('cards-status');
                if (data.cards_installed) {
                    cardsDot.className = 'status-dot';
                    cardsText.textContent = 'Installed';
                } else {
                    cardsDot.className = 'status-dot warning';
                    cardsText.textContent = 'Not Installed';
                }
            } catch (e) {
                console.error('Error checking status:', e);
            }
        }
        
        function openHA() {
            window.parent.postMessage({type: 'navigate', path: '/config/integrations'}, '*');
        }
        
        function restartHA() {
            if (confirm('Restart Home Assistant?')) {
                fetch('/api/restart', {method: 'POST'});
                alert('Restart requested. Please wait...');
            }
        }
        
        // Check status on load
        checkStatus();
        setInterval(checkStatus, 30000); // Every 30 seconds
    </script>
</body>
</html>
        """
        return web.Response(text=html, content_type='text/html')
    
    async def logs_page(self, request):
        """Logs viewer page."""
        html = """
<!DOCTYPE html>
<html>
<head>
    <title>HomeSecure Logs</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Courier New', monospace;
            background: #1e1e1e;
            color: #d4d4d4;
            padding: 20px;
        }
        .header {
            background: #2d2d30;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
        }
        h1 { color: #fff; margin-bottom: 10px; }
        .filters {
            display: flex;
            gap: 10px;
            margin-top: 15px;
        }
        select, input {
            padding: 8px 12px;
            background: #3c3c3c;
            border: 1px solid #555;
            color: #d4d4d4;
            border-radius: 4px;
        }
        .log-container {
            background: #1e1e1e;
            border: 1px solid #3c3c3c;
            border-radius: 8px;
            padding: 20px;
            height: calc(100vh - 200px);
            overflow-y: auto;
        }
        .log-entry {
            padding: 8px 0;
            border-bottom: 1px solid #2d2d30;
            font-size: 13px;
            line-height: 1.6;
        }
        .log-timestamp { color: #608b4e; }
        .log-level { font-weight: bold; margin: 0 8px; }
        .log-level.INFO { color: #4ec9b0; }
        .log-level.WARNING { color: #dcdcaa; }
        .log-level.ERROR { color: #f48771; }
        .log-level.DEBUG { color: #9cdcfe; }
        .log-component { color: #c586c0; }
        .log-message { color: #d4d4d4; }
    </style>
</head>
<body>
    <div class="header">
        <h1>🛡️ HomeSecure Logs</h1>
        <div class="filters">
            <select id="component-filter">
                <option value="">All Components</option>
                <option value="homesecure">Core</option>
                <option value="alarm_coordinator">Alarm Coordinator</option>
                <option value="lock_manager">Lock Manager</option>
                <option value="database">Database</option>
            </select>
            <select id="level-filter">
                <option value="">All Levels</option>
                <option value="DEBUG">Debug</option>
                <option value="INFO">Info</option>
                <option value="WARNING">Warning</option>
                <option value="ERROR">Error</option>
            </select>
            <input type="number" id="limit" value="100" min="10" max="1000" step="10">
            <button onclick="loadLogs()" style="padding: 8px 16px; background: #0e639c; border: none; color: white; border-radius: 4px; cursor: pointer;">Refresh</button>
        </div>
    </div>
    
    <div class="log-container" id="logs"></div>
    
    <script>
        async function loadLogs() {
            const component = document.getElementById('component-filter').value;
            const level = document.getElementById('level-filter').value;
            const limit = document.getElementById('limit').value;
            
            let url = '/api/logs?limit=' + limit;
            if (component) url += '&component=' + component;
            if (level) url += '&level=' + level;
            
            try {
                const response = await fetch(url);
                const logs = await response.json();
                
                const container = document.getElementById('logs');
                container.innerHTML = logs.map(log => `
                    <div class="log-entry">
                        <span class="log-timestamp">${log.timestamp}</span>
                        <span class="log-level ${log.level}">${log.level}</span>
                        <span class="log-component">[${log.component}]</span>
                        <span class="log-message">${log.message}</span>
                    </div>
                `).join('');
            } catch (e) {
                console.error('Error loading logs:', e);
            }
        }
        
        loadLogs();
        setInterval(loadLogs, 5000); // Auto-refresh every 5 seconds
    </script>
</body>
</html>
        """
        return web.Response(text=html, content_type='text/html')
    
    async def api_logs(self, request):
        """API endpoint for logs."""
        component = request.query.get('component')
        level = request.query.get('level')
        limit = int(request.query.get('limit', 100))
        
        db_path = "/data/homesecure_logs.db"
        
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            query = "SELECT * FROM logs WHERE 1=1"
            params = []
            
            if component:
                query += " AND component = ?"
                params.append(component)
            
            if level:
                query += " AND level = ?"
                params.append(level)
            
            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            
            cursor.execute(query, params)
            logs = [dict(row) for row in cursor.fetchall()]
            conn.close()
            
            return web.json_response(logs)
        except Exception as e:
            logger.error(f"Error fetching logs: {e}")
            return web.json_response([])
    
    async def api_status(self, request):
        """API endpoint for status."""
        integration_path = Path("/config/custom_components/homesecure")
        cards_path = Path("/config/www/homesecure-card.js")
        
        return web.json_response({
            "integration_installed": integration_path.exists(),
            "cards_installed": cards_path.exists(),
            "version": "1.0.0"
        })
    
    async def start(self):
        """Start web server."""
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', 8099)
        await site.start()
        logger.info("Web interface started on port 8099")


async def main():
    """Main entry point."""
    web_interface = HomeSecureWeb()
    await web_interface.start()
    
    # Keep running
    while True:
        await asyncio.sleep(3600)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Web interface stopped")