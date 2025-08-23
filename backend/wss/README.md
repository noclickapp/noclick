# SocketIO Handlers

Most communication between the frontend and the backend happens via the handlers in this folder. All the handlers and request routing is setup inside proxy/proxy.py where each event is mapped to its corresponding handler.

## How to add a new handler

1. Extend the SocketIOHandler class defined in schema.py with your new handler
2. Initialize the handler in the setup_config() method of SocketIOProxy (defined in ./proxy/proxy.py)
3. Based on the deployment environment (API/DATA_ENGINE/etc) update the event_handlers mapping in the proxy setup_config() method. This step introduces somewhat redundant data by redefining the events a handler can accept (this is available via the get_events method of the handler) but helps in blocking certain actions on certain environments and makes it easier to visualize all events in one place improving readability.


## Frontend Communication
All messages sent from the backend to the frontend or other locations will go through the `send_event` function defined under `wss/sender/__init__.py`. This function accepts a socket event pydantic type defined under `wss/sender/events.py`.