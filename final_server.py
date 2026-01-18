import asyncio
import json
import websockets
import mimetypes
from http import HTTPStatus
from pathlib import Path
from websockets.server import serve

# --- Server State ---
# This dictionary now maps usernames to their websocket connection
CONNECTED_CLIENTS = {}  # {username: websocket}

# --- Helper Functions ---
async def broadcast(message, exclude_username=None):
    """Broadcasts a message to all connected clients."""
    if CONNECTED_CLIENTS:
        # Create a list of websockets to send to
        targets = [ws for username, ws in CONNECTED_CLIENTS.items() if username != exclude_username]
        if targets:
            await asyncio.gather(*[ws.send(message) for ws in targets], return_exceptions=True)

async def send_private_message(message, recipient_username, sender_username):
    """Sends a private message to a specific user and a copy to the sender."""
    recipient_ws = CONNECTED_CLIENTS.get(recipient_username)
    sender_ws = CONNECTED_CLIENTS.get(sender_username)
    
    tasks = []
    if recipient_ws:
        tasks.append(recipient_ws.send(message))
    if sender_ws: # Send a copy to the sender so they see their own message
        tasks.append(sender_ws.send(message))
    
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def broadcast_user_list():
    """Compiles and sends the list of current users to all clients."""
    if CONNECTED_CLIENTS:
        user_list = list(CONNECTED_CLIENTS.keys())
        message = json.dumps({"type": "user_list", "users": user_list})
        await broadcast(message)

# --- WebSocket Connection Handler ---
async def handle_chat_connection(websocket):
    """Handles a single WebSocket connection after the initial HTTP handshake."""
    username = None
    try:
        # First message from client should be a 'join' message
        join_message = await websocket.recv()
        data = json.loads(join_message)
        
        if data.get("type") == "join":
            username = data.get("username")
            if not username or username in CONNECTED_CLIENTS:
                await websocket.close(1008, "Username is required or already taken.")
                return

            CONNECTED_CLIENTS[username] = websocket
            print(f"✔️  {username} has connected from {websocket.remote_address}.")

            join_announcement = json.dumps({"type": "info", "text": f"{username} has joined the chat!"})
            await broadcast(join_announcement)
            
            await broadcast_user_list()
        
        # Listen for subsequent messages
        async for message in websocket:
            data = json.loads(message)
            
            if data.get("type") == "pm":
                recipient = data.get("recipient")
                print(f"🔒  PM from {data.get('sender')} to {recipient}")
                await send_private_message(message, recipient, data.get('sender'))
            else: # Default to group chat
                print(f"💬  Group message from {data.get('sender')}")
                await broadcast(message, exclude_username=data.get('sender'))


    except websockets.exceptions.ConnectionClosed as e:
        print(f"Connection closed for {websocket.remote_address} (user: {username}) with code {e.code}.")
    except Exception as e:
        print(f"An error occurred with user {username}: {e}")
    finally:
        # Unregister user upon disconnection
        if username and username in CONNECTED_CLIENTS:
            del CONNECTED_CLIENTS[username]
            print(f"❌  {username} has disconnected.")
            leave_announcement = json.dumps({"type": "info", "text": f"{username} has left the chat."})
            await broadcast(leave_announcement)
            await broadcast_user_list()

# --- HTTP Request Handler ---
async def http_handler(path, request_headers):
    """Handles HTTP requests *before* the WebSocket handshake."""
    if "Upgrade" in request_headers and request_headers["Upgrade"].lower() == "websocket":
        return None  # Let the WebSocket handler take over

    if path == "/":
        filepath = Path(__file__).parent / "final_chat.html"
        try:
            with open(filepath, "rb") as f:
                content = f.read()
            content_type, _ = mimetypes.guess_type(filepath)
            headers = {"Content-Type": content_type or "text/html"}
            return HTTPStatus.OK, headers, content
        except FileNotFoundError:
            body = b"404 Not Found: final_chat.html is missing."
            return HTTPStatus.NOT_FOUND, [], body
    
    body = b"404 Not Found"
    return HTTPStatus.NOT_FOUND, [], body

# --- Main Server Start ---
async def main():
    host = "0.0.0.0"
    port = 8765
    print("Starting server...")
    async with serve(handle_chat_connection, host, port, process_request=http_handler, max_size=2097152): 
        print(f"🎉 Server is running! Open your browser to:")
        print(f"➡️   http://localhost:{port}  (for this computer)")
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            print(f"➡️   http://{local_ip}:{port}  (for other devices on the same network)")
            s.close()
        except Exception:
            print("Could not determine local IP for other devices.")
        
        await asyncio.Future()  # Run forever

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nServer is shutting down. Goodbye!")

