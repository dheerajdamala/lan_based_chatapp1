import socket
import threading
import os
import struct
import time
import configparser
import logging

# --- Configuration ---
config = configparser.ConfigParser()
try:
    config.read('config.ini')
    DISCOVERY_PORT = config.getint('Network', 'DiscoveryPort', fallback=9089)
    CHAT_PORT = config.getint('Network', 'ChatPort', fallback=9090)
    AUDIO_PORT = config.getint('Network', 'AudioPort', fallback=9091)
    VIDEO_PORT = config.getint('Network', 'VideoPort', fallback=9092)
    SCREEN_PORT = config.getint('Network', 'ScreenPort', fallback=9093)
    FILE_PORT = config.getint('Network', 'FilePort', fallback=9094)
    FILE_DIR = config.get('Server', 'FileDirectory', fallback='server_files')
    LOG_LEVEL_STR = config.get('Server', 'LogLevel', fallback='INFO').upper()
except Exception as e:
    print(f"Error reading config.ini: {e}. Using default values.")
    DISCOVERY_PORT = 9089
    CHAT_PORT = 9090
    AUDIO_PORT = 9091
    VIDEO_PORT = 9092
    SCREEN_PORT = 9093
    FILE_PORT = 9094
    FILE_DIR = 'server_files'
    LOG_LEVEL_STR = 'INFO'

# --- Logging Setup ---
log_levels = {
    'DEBUG': logging.DEBUG, 'INFO': logging.INFO, 'WARNING': logging.WARNING,
    'ERROR': logging.ERROR, 'CRITICAL': logging.CRITICAL
}
LOG_LEVEL = log_levels.get(LOG_LEVEL_STR, logging.INFO)
logging.basicConfig(level=LOG_LEVEL,
                    format='%(asctime)s - %(levelname)s - [%(threadName)s] - %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')

# --- Discovery Config ---
DISCOVERY_REQUEST = b'SERVER_DISCOVERY_REQUEST'

def get_server_lan_ip():
    """Finds the server's own LAN IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.1)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return '127.0.0.1'

def start_discovery_server():
    """Listens for UDP broadcasts and replies with the server's IP."""
    server_ip = get_server_lan_ip()
    if server_ip == '127.0.0.1':
        logging.warning("Discovery server could not find a proper LAN IP. Using 127.0.0.1.")
        logging.warning("Clients on other machines may not be able to auto-discover.")

    DISCOVERY_REPLY = f"IAM_THE_SERVER:{server_ip}".encode('utf-8')

    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind(('', DISCOVERY_PORT))
    except Exception as e:
        logging.error(f"Could not bind discovery port {DISCOVERY_PORT}. Is another instance running?", exc_info=True)
        return

    logging.info(f"Discovery server listening on port {DISCOVERY_PORT} (Replying with IP: {server_ip})")

    while True:
        try:
            data, addr = server.recvfrom(1024)
            if data == DISCOVERY_REQUEST:
                logging.info(f"Discovery request from {addr}. Replying...")
                server.sendto(DISCOVERY_REPLY, addr)
        except Exception as e:
            logging.error(f"Discovery server error", exc_info=True)

# --- Chat Server ---
# {username: {'conn': conn, 'status': 'Online'}}
chat_clients = {}
chat_lock = threading.Lock()
current_presenter_username = None # <-- NEW: Tracks the current presenter

def get_user_list_string():
    """Generates the USER_LIST string including status."""
    with chat_lock:
        if not chat_clients:
            return "USER_LIST:"
        # Format: user1=Status1,user2=Status2
        parts = [f"{name}={info['status']}" for name, info in chat_clients.items()]
        return "USER_LIST:" + ",".join(parts)

def broadcast_chat(message_bytes, sender_conn):
    """Sends a message to all chat clients except the sender."""
    with chat_lock:
        # Iterate over a copy of values to allow safe removal inside loop if needed
        clients_to_message = list(chat_clients.values())
    
    for client_info in clients_to_message:
        conn = client_info['conn']
        if conn != sender_conn:
            try:
                conn.sendall(message_bytes) # Use sendall for reliability
            except (BrokenPipeError, ConnectionResetError):
                logging.warning(f"Failed to send to a client (likely disconnected).")
            except Exception:
                 logging.error(f"Error broadcasting chat message", exc_info=True)


def handle_chat_client(conn, addr):
    global current_presenter_username
    logging.info(f"Chat connection attempt from {addr}")
    username = None
    client_info = None # To hold {'conn': conn, 'status': 'Online'}
    try:
        username_bytes = conn.recv(1024)
        if not username_bytes:
            logging.warning(f"Chat client {addr} provided no username. Disconnecting.")
            return

        username = username_bytes.decode('utf-8')

        with chat_lock:
            if not username or username in chat_clients:
                logging.warning(f"{addr} tried to connect with taken/invalid username: {username}")
                try:
                    conn.sendall(b'ERROR:USERNAME_TAKEN')
                except Exception:
                    logging.error(f"Error sending USERNAME_TAKEN to {addr}", exc_info=True)
                conn.close()
                return

            try:
                conn.sendall(b'OK')
            except Exception:
                logging.error(f"Error sending OK confirmation to {username}@{addr}", exc_info=True)
                conn.close()
                return

            logging.info(f"{username} connected from {addr}")
            # Add to client list with default status
            client_info = {'conn': conn, 'status': 'Online'}
            chat_clients[username] = client_info

        # Send current user list (with statuses) to the new client
        user_list_str = get_user_list_string()
        conn.sendall(user_list_str.encode('utf-8'))

        # Notify all other clients of the new user (including status)
        broadcast_chat(f"USER_JOIN:{username}=Online".encode('utf-8'), conn)

        # --- NEW: Inform new user if a presentation is in progress ---
        with chat_lock:
            if current_presenter_username:
                conn.sendall(f"SCREEN_START:{current_presenter_username}".encode('utf-8'))


        while True:
            message_bytes = conn.recv(1024)
            if not message_bytes:
                break # Client disconnected gracefully

            message_str = message_bytes.decode('utf-8')
            timestamp = time.strftime('%H:%M:%S') # Get timestamp

            # --- Handle Status Update ---
            if message_str.startswith("SET_STATUS:"):
                try:
                    new_status = message_str.split(":", 1)[1]
                    if new_status not in ['Online', 'Away']: # Basic validation
                        new_status = 'Online'
                    with chat_lock:
                         if username in chat_clients:
                             chat_clients[username]['status'] = new_status
                    logging.info(f"{username} set status to {new_status}")
                    broadcast_chat(f"STATUS_UPDATE:{username}={new_status}".encode('utf-8'), conn)
                except Exception:
                    logging.error(f"Error processing status update from {username}", exc_info=True)

            # --- Handle Private Messages (PM) ---
            elif message_str.startswith("PM:"):
                try:
                    _, target_user, content = message_str.split(":", 2)
                    target_conn = None
                    with chat_lock:
                        target_info = chat_clients.get(target_user)
                        if target_info:
                            target_conn = target_info['conn']

                    if target_conn:
                        # Prepend timestamp to messages being sent
                        target_conn.sendall(f"{timestamp} PM_FROM:{username}:{content}".encode('utf-8'))
                        conn.sendall(f"{timestamp} PM_TO:{target_user}:{content}".encode('utf-8')) # Confirmation
                    else:
                        conn.sendall(f"{timestamp} SYSTEM:User '{target_user}' not found or offline.".encode('utf-8'))
                except Exception:
                    logging.error(f"Error processing PM from {username}", exc_info=True)
                    conn.sendall(f"{timestamp} SYSTEM:Error processing PM.".encode('utf-8'))

            # --- NEW: Handle Screen Share Request ---
            elif message_str == "REQUEST_TO_PRESENT":
                logging.info(f"'{username}' is requesting to present.")
                with chat_lock:
                    if current_presenter_username is None:
                        # No one is presenting, grant request
                        current_presenter_username = username
                        logging.info(f"Granting present request for '{username}'.")
                        conn.sendall(b'OK_TO_PRESENT')
                        broadcast_chat(f"SCREEN_START:{username}".encode('utf-8'), conn)
                    else:
                        # Someone is presenting, ask them for permission
                        logging.info(f"Asking current presenter '{current_presenter_username}' for approval.")
                        presenter_info = chat_clients.get(current_presenter_username)
                        if presenter_info:
                            presenter_info['conn'].sendall(f"PRESENT_REQUEST_FROM:{username}".encode('utf-8'))
                        else:
                            # Presenter disconnected without cleanup? Grant request.
                            logging.warning(f"Presenter '{current_presenter_username}' not in clients. Forcibly granting to '{username}'.")
                            current_presenter_username = username
                            conn.sendall(b'OK_TO_PRESENT')
                            broadcast_chat(f"SCREEN_START:{username}".encode('utf-8'), conn)

            # --- NEW: Handle Screen Share Response ---
            elif message_str.startswith("PRESENT_RESPONSE:"):
                # Format: PRESENT_RESPONSE:Yes:RequesterName or PRESENT_RESPONSE:No:RequesterName
                try:
                    _, response, requester_name = message_str.split(":", 2)
                    logging.info(f"Presenter '{username}' responded '{response}' to '{requester_name}'.")
                    
                    with chat_lock:
                        # Ensure the person responding is STILL the presenter
                        if username != current_presenter_username:
                            logging.warning(f"'{username}' responded, but is no longer presenter. Ignoring.")
                            continue

                        requester_info = chat_clients.get(requester_name)
                        if not requester_info:
                            logging.warning(f"Requester '{requester_name}' no longer connected. Ignoring response.")
                            continue

                        if response == "Yes":
                            logging.info(f"Transferring presentation from '{username}' to '{requester_name}'.")
                            # 1. Tell new presenter it's OK
                            requester_info['conn'].sendall(b'OK_TO_PRESENT')
                            # 2. Tell old presenter to stop
                            conn.sendall(b'SCREEN_STOP_REQUESTED')
                            # 3. Update server state
                            current_presenter_username = requester_name
                            # 4. Tell everyone ELSE (including old presenter) to view the new stream
                            broadcast_chat(f"SCREEN_START:{requester_name}".encode('utf-8'), requester_info['conn'])
                        else:
                            # Response was "No", tell requester
                            requester_info['conn'].sendall(b'PRESENT_REQUEST_DENIED')

                except Exception:
                    logging.error(f"Error processing PRESENT_RESPONSE from {username}", exc_info=True)

            # --- NEW: Handle Stop Sharing ---
            elif message_str == "STOP_SHARING":
                logging.info(f"'{username}' is stopping their presentation.")
                with chat_lock:
                    if username == current_presenter_username:
                        current_presenter_username = None
                        broadcast_chat(b'SCREEN_STOP', None) # Tell everyone (no exception)
                    else:
                        logging.warning(f"'{username}' sent STOP_SHARING, but wasn't the presenter.")

            # --- Handle Public Text Messages ---
            else:
                # Prepend timestamp and username before broadcasting
                formatted_message = f"{timestamp} {username}: {message_str}"
                logging.debug(f"Public from {username}: {message_str}")
                broadcast_chat(formatted_message.encode('utf-8'), conn)

    except (ConnectionResetError, BrokenPipeError):
         logging.info(f"Client {username}@{addr} disconnected abruptly.")
    except Exception:
        logging.error(f"Error in chat handler for {username}@{addr}", exc_info=True)
    finally:
        if username:
            removed = False
            presenter_was_this_user = False
            with chat_lock:
                if username in chat_clients:
                    del chat_clients[username]
                    removed = True
                # --- NEW: Check if disconnecting user was the presenter ---
                if username == current_presenter_username:
                    current_presenter_username = None
                    presenter_was_this_user = True
                    
            if removed:
                 broadcast_chat(f"USER_LEAVE:{username}".encode('utf-8'), None) # Notify all
                 logging.info(f"Disconnected: {username} at {addr}")
            
            if presenter_was_this_user:
                logging.info(f"Presenter '{username}' disconnected. Stopping all screen sharing.")
                broadcast_chat(b'SCREEN_STOP', None) # Tell everyone
                 
        try:
            conn.close()
        except Exception:
            pass # Socket might already be closed

def start_chat_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind(('', CHAT_PORT))
    except Exception as e:
        logging.error(f"Could not bind chat port {CHAT_PORT}. Is another instance running?", exc_info=True)
        return
    server.listen()
    logging.info(f"Chat server listening on port {CHAT_PORT}")
    while True:
        try:
            conn, addr = server.accept()
            threading.Thread(target=handle_chat_client, args=(conn, addr), name=f"Chat-{addr[0]}:{addr[1]}", daemon=True).start()
        except Exception:
             logging.error(f"Error accepting chat connection", exc_info=True)


# --- Audio Server ---
audio_clients = set()
audio_lock = threading.Lock()

def start_audio_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind(('', AUDIO_PORT))
    except Exception as e:
        logging.error(f"Could not bind audio port {AUDIO_PORT}.", exc_info=True)
        return
    logging.info(f"Audio server listening on port {AUDIO_PORT}")
    while True:
        try:
            data, addr = server.recvfrom(4096) # Adjust buffer size if needed
            with audio_lock:
                if addr not in audio_clients:
                    logging.info(f"New audio connection from {addr}")
                    audio_clients.add(addr)
                # Broadcast to all *other* clients
                # Make a copy to avoid issues if set changes during iteration
                current_clients = list(audio_clients)
            for client_addr in current_clients:
                if client_addr != addr:
                    server.sendto(data, client_addr)
        except ConnectionResetError:
            # Common UDP error on Windows when client disconnects, usually safe to ignore
            logging.debug(f"Audio connection reset by peer {addr}.")
            with audio_lock:
                audio_clients.discard(addr)
        except Exception:
            logging.error("Error in audio server loop", exc_info=True)


# --- Video Server ---
video_clients = set()
video_lock = threading.Lock()

def start_video_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind(('', VIDEO_PORT))
    except Exception as e:
         logging.error(f"Could not bind video port {VIDEO_PORT}.", exc_info=True)
         return
    logging.info(f"Video server listening on port {VIDEO_PORT}")
    BUFFER_SIZE = 65536 # Max UDP datagram size
    while True:
        try:
            data, addr = server.recvfrom(BUFFER_SIZE)
            with video_lock:
                if addr not in video_clients:
                    logging.info(f"New video connection from {addr}")
                    video_clients.add(addr)
                current_clients = list(video_clients)
            for client_addr in current_clients:
                 if client_addr != addr:
                    server.sendto(data, client_addr)
        except ConnectionResetError:
             logging.debug(f"Video connection reset by peer {addr}.")
             with video_lock:
                video_clients.discard(addr)
        except Exception:
             logging.error("Error in video server loop", exc_info=True)


# --- Screen Share Server ---
SCREEN_PORT = 9093
screen_presenter_socket = None
screen_viewers = []
screen_lock = threading.Lock()

def broadcast_to_viewers(data, _sender_conn):
    with screen_lock:
        if _sender_conn != screen_presenter_socket:
            logging.warning("Broadcast attempt from non-presenter ignored.")
            return
        # Iterate over a copy in case of disconnections during broadcast
        current_viewers = list(screen_viewers)

    for viewer_conn in current_viewers:
        try:
            viewer_conn.sendall(data)
        except (BrokenPipeError, ConnectionResetError):
            logging.info("Screen viewer disconnected during broadcast.")
            with screen_lock:
                if viewer_conn in screen_viewers:
                    screen_viewers.remove(viewer_conn)
        except Exception:
            logging.error("Error broadcasting screen data to viewer", exc_info=True)
            with screen_lock:
                 if viewer_conn in screen_viewers:
                    screen_viewers.remove(viewer_conn)


def handle_screen_client(conn, addr):
    global screen_presenter_socket
    logging.info(f"Screen share connection from {addr}")
    client_role = "Unknown"
    try:
        role = conn.recv(1024)
        if role == b'PRESENTER':
            client_role = "Presenter"
            with screen_lock:
                if screen_presenter_socket is None:
                    screen_presenter_socket = conn
                    logging.info(f"{addr} connected as SCREEN PRESENTER")
                else:
                    logging.warning(f"{addr} tried to connect as presenter, but one is active.")
                    conn.sendall(b'ERROR: Presenter busy')
                    conn.close()
                    return

            # Presenter loop: receive frame length, then frame data
            while True:
                len_data = conn.recv(4)
                if not len_data or len(len_data) < 4:
                    break # Presenter disconnected or sent invalid data
                frame_size = struct.unpack('!I', len_data)[0]

                # Basic sanity check for frame size
                if frame_size <= 0 or frame_size > 20 * 1024 * 1024: # e.g., Max 20MB frame
                     logging.warning(f"Presenter {addr} sent invalid frame size: {frame_size}. Disconnecting.")
                     break

                frame_data = b''
                while len(frame_data) < frame_size:
                    chunk = conn.recv(min(4096, frame_size - len(frame_data))) # Read in chunks
                    if not chunk:
                        break # Presenter disconnected during frame send
                    frame_data += chunk

                if len(frame_data) != frame_size:
                     logging.warning(f"Presenter {addr} disconnected mid-frame.")
                     break

                broadcast_to_viewers(len_data + frame_data, conn)

        elif role == b'VIEWER':
            client_role = "Viewer"
            with screen_lock:
                screen_viewers.append(conn)
                logging.info(f"{addr} connected as SCREEN VIEWER")

            # Viewer loop: Keep connection alive, break on disconnect/error
            while True:
                conn.settimeout(60.0) # Check every 60 seconds
                try:
                    ping_data = conn.recv(1)
                    if not ping_data:
                        break # Viewer disconnected gracefully
                except socket.timeout:
                    continue # No data received, but connection is likely still alive
                except (ConnectionResetError, BrokenPipeError):
                    break # Viewer disconnected abruptly
                finally:
                    conn.settimeout(None) # Reset timeout for next operation

        else:
             logging.warning(f"Unknown role received from screen client {addr}: {role}")

    except (ConnectionResetError, BrokenPipeError):
         logging.info(f"Screen client {addr} ({client_role}) disconnected abruptly.")
    except Exception:
        logging.error(f"Error handling screen client {addr} ({client_role})", exc_info=True)
    finally:
        with screen_lock:
            if conn == screen_presenter_socket:
                screen_presenter_socket = None
                logging.info(f"Screen presenter {addr} disconnected.")
            if conn in screen_viewers:
                screen_viewers.remove(conn)
                logging.info(f"Screen viewer {addr} disconnected.")
        try:
            conn.close()
        except Exception:
            pass

def start_screen_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind(('', SCREEN_PORT))
    except Exception as e:
        logging.error(f"Could not bind screen port {SCREEN_PORT}.", exc_info=True)
        return
    server.listen(5) # Allow a small backlog of connections
    logging.info(f"Screen server listening on port {SCREEN_PORT}")
    while True:
        try:
            conn, addr = server.accept()
            threading.Thread(target=handle_screen_client, args=(conn, addr), name=f"Screen-{addr[0]}:{addr[1]}", daemon=True).start()
        except Exception:
             logging.error("Error accepting screen connection", exc_info=True)


# --- File Share Server ---
if not os.path.exists(FILE_DIR):
    try:
        os.makedirs(FILE_DIR)
        logging.info(f"Created server file directory: {FILE_DIR}")
    except Exception:
         logging.error(f"Failed to create server file directory: {FILE_DIR}", exc_info=True)

file_clients = []
file_lock = threading.Lock()
available_files = [] # Cache of files in FILE_DIR

def update_file_list():
    """Scans the FILE_DIR and updates the global available_files list."""
    global available_files
    try:
        with file_lock: # Protect access during update
            available_files = [f for f in os.listdir(FILE_DIR) if os.path.isfile(os.path.join(FILE_DIR, f))]
            logging.debug(f"Updated available files: {available_files}")
    except Exception:
        logging.error(f"Error scanning file directory: {FILE_DIR}", exc_info=True)
        available_files = [] # Reset on error

def broadcast_file_update(message_bytes, sender_conn):
    """Sends file list updates (NEW_FILE, FILE_DELETED) to clients."""
    with file_lock:
        current_clients = list(file_clients) # Copy for safe iteration

    for client_conn in current_clients:
        if client_conn != sender_conn:
            try:
                client_conn.sendall(message_bytes)
            except (BrokenPipeError, ConnectionResetError):
                 logging.info("File client disconnected during broadcast.")
                 with file_lock:
                     if client_conn in file_clients:
                        file_clients.remove(client_conn)
            except Exception:
                 logging.error("Error broadcasting file update", exc_info=True)
                 with file_lock:
                     if client_conn in file_clients:
                        file_clients.remove(client_conn)


def handle_file_client(conn, addr):
    logging.info(f"File share connection from {addr}")
    with file_lock:
        file_clients.append(conn)

    # Initial file list send
    update_file_list() # Ensure list is current before sending
    try:
        # Send file list as a single message with a newline delimiter
        file_list_str = ",".join(available_files)
        conn.sendall(f"FILE_LIST:{file_list_str}\n".encode('utf-8'))
    except Exception:
        logging.error(f"Error sending initial file list to {addr}", exc_info=True)
        with file_lock:
            file_clients.remove(conn)
        conn.close()
        return

    buffer = "" # Buffer for receiving commands line by line
    try:
        while True:
            try:
                conn.settimeout(300.0) # 5 minutes timeout for inactivity
                data = conn.recv(1024)
                conn.settimeout(None) # Reset timeout
                if not data:
                    break # Client disconnected gracefully
                buffer += data.decode('utf-8')
            except socket.timeout:
                 logging.debug(f"File client {addr} timed out waiting for command.")
                 break # Disconnect inactive client
            except UnicodeDecodeError:
                 logging.warning(f"Received non-UTF8 data from file client {addr}. Ignoring.")
                 buffer = "" # Clear potentially corrupted buffer
                 continue

            # Process all newline-terminated commands in the buffer
            while '\n' in buffer:
                cmd_data, buffer = buffer.split('\n', 1)
                if not cmd_data: continue # Skip empty lines

                logging.debug(f"Received file command from {addr}: {cmd_data[:100]}") # Log truncated command

                # --- Handle UPLOAD ---
                if cmd_data.startswith('UPLOAD:'):
                    try:
                        parts = cmd_data.split(':', 2)
                        if len(parts) != 3: raise ValueError("Invalid UPLOAD format")
                        filename_raw = parts[1]
                        filesize_str = parts[2]
                        # Sanitize filename
                        filename = os.path.basename(filename_raw)
                        if not filename: raise ValueError("Empty filename") # Prevent saving as just directory
                        filesize = int(filesize_str)
                        if filesize < 0: raise ValueError("Invalid filesize")

                        filepath = os.path.join(FILE_DIR, filename)

                        count = 1
                        base, ext = os.path.splitext(filepath)
                        while os.path.exists(filepath):
                            filepath = f"{base}_{count}{ext}"
                            filename = os.path.basename(filepath) # Update filename if changed
                            count += 1
                        
                        logging.info(f"Receiving file '{filename}' ({filesize} bytes) from {addr} to {filepath}")

                        conn.sendall(b'OK\n') # Acknowledge upload start

                        received_bytes = 0
                        with open(filepath, 'wb') as f:
                            while received_bytes < filesize:
                                conn.settimeout(60.0) # Timeout for receiving file data
                                chunk = conn.recv(min(4096, filesize - received_bytes))
                                conn.settimeout(None)
                                if not chunk:
                                    raise ConnectionError("Client disconnected during upload")
                                f.write(chunk)
                                received_bytes += len(chunk)

                        if received_bytes == filesize:
                            logging.info(f"Successfully received {filename} from {addr}")
                            update_file_list()
                            broadcast_file_update(f"NEW_FILE:{filename}\n".encode('utf-8'), conn)
                        else:
                             raise IOError(f"Incomplete upload for {filename}. Expected {filesize}, got {received_bytes}")

                    except (ValueError, IndexError) as ve:
                         logging.warning(f"Invalid UPLOAD command from {addr}: {cmd_data} ({ve})")
                         try: conn.sendall(b"ERROR:Invalid UPLOAD command\n")
                         except Exception: pass
                    except ConnectionError as ce:
                         logging.warning(f"{ce} for {filename}. Deleting incomplete file.")
                         if os.path.exists(filepath): os.remove(filepath)
                         break # Exit handler loop
                    except Exception as upload_err:
                         logging.error(f"Error receiving file from {addr}", exc_info=True)
                         if os.path.exists(filepath): # Attempt cleanup
                             try: os.remove(filepath)
                             except Exception: logging.error("Failed to delete incomplete upload.", exc_info=True)
                         try: conn.sendall(f"ERROR:Upload failed: {upload_err}\n".encode('utf-8'))
                         except Exception: pass


                # --- Handle DOWNLOAD ---
                elif cmd_data.startswith('DOWNLOAD:'):
                    try:
                        parts = cmd_data.split(':', 1)
                        if len(parts) != 2: raise ValueError("Invalid DOWNLOAD format")
                        filename_req = os.path.basename(parts[1]) # Sanitize
                        if not filename_req: raise ValueError("Empty filename requested")

                        filepath = os.path.join(FILE_DIR, filename_req)
                        logging.debug(f"Download request for '{filename_req}' from {addr}")

                        if os.path.exists(filepath) and os.path.isfile(filepath):
                            filesize = os.path.getsize(filepath)
                            logging.info(f"Sending file '{filename_req}' ({filesize} bytes) to {addr}")
                            conn.sendall(f"FILE_DATA:{filesize}\n".encode('utf-8'))

                            conn.settimeout(30.0)
                            client_confirm = conn.recv(1024)
                            conn.settimeout(None)
                            if client_confirm != b'OK':
                                logging.warning(f"Client {addr} did not confirm download start for {filename_req}. Aborting.")
                                continue 

                            with open(filepath, 'rb') as f:
                                while chunk := f.read(4096):
                                    conn.sendall(chunk)
                            logging.info(f"Finished sending {filename_req} to {addr}")
                        else:
                            logging.warning(f"File '{filename_req}' not found for download request from {addr}")
                            conn.sendall(b'ERROR:File not found\n')

                    except (ValueError, IndexError) as ve:
                         logging.warning(f"Invalid DOWNLOAD command from {addr}: {cmd_data} ({ve})")
                         try: conn.sendall(b"ERROR:Invalid DOWNLOAD command\n")
                         except Exception: pass
                    except Exception as download_err:
                         logging.error(f"Error sending file to {addr}", exc_info=True)
                         break # Assume connection is lost


                # --- Handle DELETE ---
                elif cmd_data.startswith('DELETE:'):
                     try:
                        parts = cmd_data.split(':', 1)
                        if len(parts) != 2: raise ValueError("Invalid DELETE format")
                        filename_req = os.path.basename(parts[1]) # Sanitize
                        if not filename_req: raise ValueError("Empty filename requested")

                        filepath = os.path.join(FILE_DIR, filename_req)
                        logging.info(f"Delete request for '{filename_req}' from {addr}")

                        if os.path.exists(filepath) and os.path.isfile(filepath):
                            os.remove(filepath)
                            logging.info(f"Deleted file: {filename_req}")
                            update_file_list()
                            broadcast_file_update(f"FILE_DELETED:{filename_req}\n".encode('utf-8'), None) # Broadcast to all
                            conn.sendall(b'OK:File deleted\n') # Confirmation to requester
                        else:
                            logging.warning(f"File '{filename_req}' not found for delete request from {addr}")
                            conn.sendall(b'ERROR:File not found\n')

                     except (ValueError, IndexError) as ve:
                         logging.warning(f"Invalid DELETE command from {addr}: {cmd_data} ({ve})")
                         try: conn.sendall(b"ERROR:Invalid DELETE command\n")
                         except Exception: pass
                     except Exception as delete_err:
                         logging.error(f"Error deleting file {filename_req}", exc_info=True)
                         try: conn.sendall(f"ERROR:Could not delete file: {delete_err}\n".encode('utf-8'))
                         except Exception: pass


                else:
                    logging.warning(f"Unknown file command from {addr}: {cmd_data}")


    except (ConnectionResetError, BrokenPipeError):
         logging.info(f"File client {addr} disconnected abruptly.")
    except Exception:
        logging.error(f"Error in file handler for {addr}", exc_info=True)
    finally:
        with file_lock:
            if conn in file_clients:
                 file_clients.remove(conn)
        try:
            conn.close()
        except Exception: pass
        logging.info(f"File client {addr} disconnected.")


def start_file_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind(('', FILE_PORT))
    except Exception as e:
        logging.error(f"Could not bind file port {FILE_PORT}.", exc_info=True)
        return
    server.listen(5)
    logging.info(f"File server listening on port {FILE_PORT} (Serving from: {FILE_DIR})")
    while True:
        try:
            conn, addr = server.accept()
            threading.Thread(target=handle_file_client, args=(conn, addr), name=f"File-{addr[0]}:{addr[1]}", daemon=True).start()
        except Exception:
             logging.error("Error accepting file connection", exc_info=True)

# --- Main Server Start ---
if __name__ == "__main__":
    print("--- Starting All-in-One LAN Server ---")
    logging.info("Server starting...")

    # Start all servers in daemon threads
    threading.Thread(target=start_discovery_server, name="DiscoveryThread", daemon=True).start()
    threading.Thread(target=start_chat_server, name="ChatThread", daemon=True).start()
    threading.Thread(target=start_audio_server, name="AudioThread", daemon=True).start()
    threading.Thread(target=start_video_server, name="VideoThread", daemon=True).start()
    threading.Thread(target=start_screen_server, name="ScreenThread", daemon=True).start()
    threading.Thread(target=start_file_server, name="FileThread", daemon=True).start()

    print("\nAll servers initialized.")
    print(f"  Discovery: {DISCOVERY_PORT} (UDP)")
    print(f"  Chat:      {CHAT_PORT} (TCP)")
    print(f"  Audio:     {AUDIO_PORT} (UDP)")
    print(f"  Video:     {VIDEO_PORT} (UDP)")
    print(f"  Screen:    {SCREEN_PORT} (TCP)")
    print(f"  Files:     {FILE_PORT} (TCP) -> '{FILE_DIR}'")
    print(f"  Log Level: {LOG_LEVEL_STR}")
    print("\nPress Ctrl+C to stop.")
    logging.info("All servers started successfully.")

    try:
        # Keep main thread alive
        while True:
            time.sleep(3600) # Sleep for an hour
    except KeyboardInterrupt:
        print("\nCtrl+C detected. Shutting down servers...")
        logging.info("Shutdown initiated by user.")
        # Threads are daemons, they will exit automatically when the main thread ends.
        print("Goodbye.")