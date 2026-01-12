class ClientState:
    def __init__(self, client_id, writer, info):
        self.client_id = client_id
        self.writer = writer
        self.info = info
        self.last_seen = 0
        self.active_tasks = 0
