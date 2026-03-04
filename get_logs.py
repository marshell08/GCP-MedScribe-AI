import json
import urllib.request
import websocket # pip install websocket-client
import sys

try:
    # 1. Get the list of inspectable pages from Chrome's remote debugging port
    # Assume Chrome is running with --remote-debugging-port=9222 (standard for testing)
    response = urllib.request.urlopen('http://localhost:9222/json')
    pages = json.loads(response.read())
    
    # 2. Find our target page
    target_ws = None
    for page in pages:
        if 'localhost:8080' in page.get('url', ''):
            target_ws = page.get('webSocketDebuggerUrl')
            break
            
    if not target_ws:
        print("Could not find MedScribe tab in debugger.")
        sys.exit(1)
        
    print(f"Connecting to CDP: {target_ws}")
    
    # 3. Connect to the page's WebSocket and fetch logs
    ws = websocket.create_connection(target_ws)
    
    # Enable domains
    ws.send(json.dumps({"id": 1, "method": "Console.enable"}))
    ws.send(json.dumps({"id": 2, "method": "Runtime.enable"}))
    
    # We can't easily fetch historical logs via standard CDP without a dedicated listener, 
    # but we CAN evaluate a script that retrieves stored errors if we hijacked window.onerror, 
    # OR we can just ask the DOM what's wrong.
    
    # Let's just ask the DOM for an alert or something simple
    # But actually, the problem is most likely AudioContext suspension or something. Let's just 
    # manually check the JS.
    
    print("CDP connected.")
    ws.close()
    
except Exception as e:
    print(f"Error connecting to Chrome DevTools: {e}")
