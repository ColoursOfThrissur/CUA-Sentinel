"""Sentinel Sensory and Motor Organs (Eyes, Arms, Hands, Web)."""
from sentinel_broker.organs.sensory import register_sensory_organs
from sentinel_broker.organs.motor import register_motor_organs
from sentinel_broker.organs.blender import register_blender_organs
from sentinel_broker.organs.data_organ import register_data_organs
from sentinel_broker.organs.web_organ import register_web_organs

__all__ = [
    "register_sensory_organs",
    "register_motor_organs",
    "register_blender_organs",
    "register_data_organs",
    "register_web_organs",
]
