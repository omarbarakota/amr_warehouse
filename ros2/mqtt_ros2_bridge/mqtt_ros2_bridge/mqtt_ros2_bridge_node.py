#!/usr/bin/env python3
"""
MQTT to ROS 2 Bidirectional Bridge Node

This node bridges MQTT topics to ROS 2 topics and vice versa, enabling
communication between MQTT clients and ROS 2 applications.

Topic Mapping:
- Robot Commands (MQTT -> ROS 2):
  /robot/move -> /robot/move (String)
  /robot/goal -> /robot/goal (String, JSON)
  /robot/lift -> /robot/lift (String)
  /robot/gripper -> /robot/gripper (String)
  /robot/grippermove -> /robot/grippermove (String)
  /robot/emergency -> /robot/emergency (String)
  /robot/arm/move -> /robot/arm/move (String)
  /robot/arm/gripper -> /robot/arm/gripper (String)

- Status Topics (ROS 2 -> MQTT):
  /robot/connection -> /robot/connection (String)
  /robot/status -> /robot/status (String, JSON)

All ROS 2 topics use std_msgs/String for compatibility.
"""

import json
import logging
import time
from typing import Any, Dict, Optional

import paho.mqtt.client as mqtt
import rclpy
from rclpy.node import Node
from std_msgs.msg import String


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(asctime)s - %(name)s - %(message)s'
)
logger = logging.getLogger('mqtt_ros2_bridge')


def normalize_topic(topic: Optional[str]) -> str:
    """Normalize topic names to a consistent leading-slash format."""
    if topic is None:
        return '/'

    topic = str(topic).strip()
    if not topic:
        return '/'

    parts = [part for part in topic.split('/') if part]
    if not parts:
        return '/'

    return '/' + '/'.join(parts)


class MQTTRos2Bridge(Node):
    """
    Bidirectional bridge between MQTT and ROS 2.
    
    This node:
    1. Connects to an MQTT broker
    2. Subscribes to robot command MQTT topics
    3. Republishes MQTT messages to ROS 2 topics
    4. Subscribes to ROS 2 status topics
    5. Republishes ROS 2 messages to MQTT topics
    """

    # MQTT -> ROS 2 (command topics, from web app to robot)
    MQTT_TO_ROS_TOPICS = {
        '/robot/move': 'move',
        '/robot/goal': 'goal',
        '/robot/lift': 'lift',
        '/robot/gripper': 'gripper',
        '/robot/grippermove': 'grippermove',
        '/robot/emergency': 'emergency',
        '/robot/arm/move': 'arm_move',
        '/robot/arm/gripper': 'arm_gripper',
    }

    # ROS 2 -> MQTT (status topics, from robot to web app)
    ROS_TO_MQTT_TOPICS = {
        '/robot/connection': 'connection',
        '/robot/status': 'status',
    }

    def __init__(self):
        super().__init__('mqtt_ros2_bridge')

        # Get parameters from launch/config
        self.declare_parameter('mqtt_broker_host', 'localhost')
        self.declare_parameter('mqtt_broker_port', 1883)
        self.declare_parameter('mqtt_topic_prefix', '')
        self.declare_parameter('client_id', 'mqtt_ros2_bridge')
        self.declare_parameter('mqtt_reconnect_interval', 5)
        self.declare_parameter('publish_timestamps', False)

        self.mqtt_host = self.get_parameter('mqtt_broker_host').value
        self.mqtt_port = self.get_parameter('mqtt_broker_port').value
        raw_prefix = self.get_parameter('mqtt_topic_prefix').value
        self.mqtt_prefix = normalize_topic(raw_prefix) if raw_prefix else ''
        self.client_id = self.get_parameter('client_id').value
        self.reconnect_interval = self.get_parameter('mqtt_reconnect_interval').value
        self.publish_timestamps = self.get_parameter('publish_timestamps').value

        self.get_logger().info(
            f'MQTT Bridge initialized: broker={self.mqtt_host}:{self.mqtt_port}, '
            f'prefix={self.mqtt_prefix or "(none)"}'
        )

        # MQTT client
        self.mqtt_client = mqtt.Client(
            client_id=self.client_id,
            protocol=mqtt.MQTTv311,
        )
        self.mqtt_client.on_connect = self._on_mqtt_connect
        self.mqtt_client.on_disconnect = self._on_mqtt_disconnect
        self.mqtt_client.on_message = self._on_mqtt_message
        self.mqtt_client.reconnect_delay_set(min_delay=1, max_delay=30)
        self.mqtt_connected = False
        self.mqtt_loop_started = False

        # ROS 2 subscribers (listen to status topics from ROS apps)
        self.ros_subscribers: Dict[str, Any] = {}
        self._create_ros_subscribers()

        # ROS 2 publishers (publish commands from MQTT to ROS)
        self.ros_publishers: Dict[str, Any] = {}
        self._create_ros_publishers()

        # Timer for MQTT connection management
        self.create_timer(1.0, self._mqtt_connection_loop)

        # Timer to periodically publish connection status
        self.create_timer(5.0, self._publish_connection_status)

        self.get_logger().info('MQTT-ROS 2 Bridge node started')

    def _create_ros_publishers(self):
        """Create ROS 2 publishers for each command topic."""
        for mqtt_topic in self.MQTT_TO_ROS_TOPICS.keys():
            ros_topic = normalize_topic(mqtt_topic)
            self.ros_publishers[ros_topic] = self.create_publisher(
                String, ros_topic, qos_profile=10
            )
            self.get_logger().debug(f'Created publisher for {ros_topic}')

    def _create_ros_subscribers(self):
        """Create ROS 2 subscribers for each status topic."""
        for ros_topic in self.ROS_TO_MQTT_TOPICS.keys():
            normalized_ros_topic = normalize_topic(ros_topic)
            callback = self._create_ros_callback(normalized_ros_topic)
            self.ros_subscribers[normalized_ros_topic] = self.create_subscription(
                String, normalized_ros_topic, callback, qos_profile=10
            )
            self.get_logger().debug(f'Created subscription for {ros_topic}')

    def _create_ros_callback(self, ros_topic: str):
        """Factory for creating ROS 2 message callbacks."""
        def callback(msg: String):
            self._on_ros_message(ros_topic, msg)
        return callback

    def _on_ros_message(self, ros_topic: str, msg: String):
        """Handle messages from ROS 2 topics."""
        try:
            # Map ROS topic to MQTT topic
            normalized_ros_topic = normalize_topic(ros_topic)
            mqtt_topic = self._format_mqtt_topic(normalized_ros_topic)
            payload = msg.data

            if self.mqtt_connected:
                self.mqtt_client.publish(mqtt_topic, payload, qos=1, retain=False)
                self.get_logger().debug(
                    f'Published to MQTT: {mqtt_topic} = {payload}'
                )
            else:
                self.get_logger().warning(
                    f'MQTT not connected; dropping message to {mqtt_topic}'
                )
        except Exception as e:
            self.get_logger().error(
                f'Error processing ROS message from {ros_topic}: {e}'
            )

    def _mqtt_connection_loop(self):
        """Manage MQTT connection state."""
        try:
            if not self.mqtt_connected and not self.mqtt_loop_started:
                self.get_logger().info(
                    f'Connecting to MQTT broker at {self.mqtt_host}:{self.mqtt_port}...'
                )
                self.mqtt_client.connect(self.mqtt_host, self.mqtt_port, keepalive=60)
                self.mqtt_client.loop_start()
                self.mqtt_loop_started = True
            elif not self.mqtt_connected and self.mqtt_loop_started:
                # Already tried to connect, wait for callback
                pass
        except Exception as e:
            self.get_logger().error(
                f'MQTT connection error: {e}. Retrying in {self.reconnect_interval}s...'
            )
            self.mqtt_loop_started = False

    def _on_mqtt_connect(self, client, userdata, flags, rc):
        """MQTT connection callback."""
        if rc == 0:
            self.mqtt_connected = True
            self.get_logger().info('Connected to MQTT broker successfully')

            # Subscribe to all command topics
            for mqtt_topic in self.MQTT_TO_ROS_TOPICS.keys():
                formatted_topic = self._format_mqtt_topic(mqtt_topic)
                client.subscribe(formatted_topic, qos=1)
                self.get_logger().info(f'Subscribed to MQTT topic: {formatted_topic}')

            # Publish initial connection status
            self._publish_connection_status_now()
        else:
            self.mqtt_connected = False
            self.get_logger().error(f'Failed to connect to MQTT broker. Code: {rc}')

    def _on_mqtt_disconnect(self, client, userdata, rc):
        """MQTT disconnection callback."""
        self.mqtt_connected = False
        if rc != 0:
            self.get_logger().warning(
                f'Unexpected MQTT disconnection (code: {rc}). '
                f'Will attempt to reconnect...'
            )

    def _on_mqtt_message(self, client, userdata, msg: mqtt.MQTTMessage):
        """Handle incoming MQTT messages."""
        try:
            mqtt_topic = msg.topic
            payload = msg.payload.decode('utf-8')

            # Map MQTT topic to ROS 2 topic
            ros_topic = self._map_mqtt_to_ros_topic(mqtt_topic)

            if ros_topic and ros_topic in self.ros_publishers:
                # Create and publish ROS 2 message
                ros_msg = String()
                ros_msg.data = payload

                # Add timestamp if enabled
                if self.publish_timestamps:
                    try:
                        ros_msg.data = json.dumps({
                            'payload': payload,
                            'timestamp': time.time(),
                            'mqtt_topic': mqtt_topic
                        })
                    except Exception:
                        pass  # Fall back to plain payload

                self.ros_publishers[ros_topic].publish(ros_msg)
                self.get_logger().debug(
                    f'Published to ROS: {ros_topic} (from MQTT: {mqtt_topic}) = {payload}'
                )
            else:
                self.get_logger().warning(
                    f'Received message on unmapped MQTT topic: {mqtt_topic}'
                )
        except Exception as e:
            self.get_logger().error(
                f'Error processing MQTT message: {e}'
            )

    def _map_mqtt_to_ros_topic(self, mqtt_topic: str) -> Optional[str]:
        """Convert MQTT topic to ROS 2 topic."""
        normalized_topic = normalize_topic(mqtt_topic)

        if self.mqtt_prefix:
            normalized_prefix = normalize_topic(self.mqtt_prefix)
            if normalized_topic.startswith(normalized_prefix + '/'):
                normalized_topic = normalized_topic[len(normalized_prefix):]
            elif normalized_topic == normalized_prefix:
                normalized_topic = '/'

        normalized_topic = normalize_topic(normalized_topic)

        # Look up in mapping
        return self.MQTT_TO_ROS_TOPICS.get(normalized_topic)

    def _format_mqtt_topic(self, topic: str) -> str:
        """Add prefix to topic if configured."""
        normalized_topic = normalize_topic(topic)
        if self.mqtt_prefix:
            return normalize_topic(self.mqtt_prefix) + normalized_topic
        return normalized_topic

    def _publish_connection_status(self):
        """Periodically publish connection status (timer callback)."""
        if self.ros_publishers.get('/robot/connection'):
            self._publish_connection_status_now()

    def _publish_connection_status_now(self):
        """Publish current connection status immediately."""
        try:
            status_msg = String()
            status_msg.data = 'connected' if self.mqtt_connected else 'disconnected'

            if '/robot/connection' in self.ros_publishers:
                self.ros_publishers['/robot/connection'].publish(status_msg)
                self.get_logger().debug(
                    f'Published connection status: {status_msg.data}'
                )
        except Exception as e:
            self.get_logger().error(f'Error publishing connection status: {e}')

    def destroy_node(self):
        """Clean up resources."""
        self.get_logger().info('Shutting down MQTT-ROS 2 Bridge...')
        if self.mqtt_loop_started:
            self.mqtt_client.loop_stop()
        if self.mqtt_connected:
            self.mqtt_client.disconnect()
        super().destroy_node()


def main(args=None):
    """Main entry point."""
    rclpy.init(args=args)

    try:
        bridge = MQTTRos2Bridge()
        rclpy.spin(bridge)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.error(f'Fatal error in bridge: {e}', exc_info=True)
    finally:
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
