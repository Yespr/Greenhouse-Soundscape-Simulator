class MqttClient:
    """Placeholder for Home Assistant/MQTT integration.

    The backend depends on this small boundary instead of a concrete MQTT
    library, so v2 can add paho-mqtt or asyncio-mqtt without touching API code.
    """

    def __init__(self) -> None:
        self.enabled = False

    def start(self) -> None:
        if not self.enabled:
            return

    def stop(self) -> None:
        if not self.enabled:
            return

    def publish_state(self, topic: str, payload: str) -> None:
        if not self.enabled:
            return
