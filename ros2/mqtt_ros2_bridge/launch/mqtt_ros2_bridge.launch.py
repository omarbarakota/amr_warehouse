#!/usr/bin/env python3
"""
Launch file for the MQTT to ROS 2 bridge node.

Usage:
    ros2 launch mqtt_ros2_bridge mqtt_ros2_bridge.launch.py
    ros2 launch mqtt_ros2_bridge mqtt_ros2_bridge.launch.py mqtt_host:=192.168.1.100 mqtt_port:=1883
"""

import os

from ament_index_python import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    """Generate launch description."""
    
    # Get package directory
    package_dir = get_package_share_directory('mqtt_ros2_bridge')
    
    # Declare launch arguments
    mqtt_host_arg = DeclareLaunchArgument(
        'mqtt_host',
        default_value='localhost',
        description='MQTT broker hostname or IP address'
    )
    
    mqtt_port_arg = DeclareLaunchArgument(
        'mqtt_port',
        default_value='1883',
        description='MQTT broker port'
    )
    
    mqtt_prefix_arg = DeclareLaunchArgument(
        'mqtt_topic_prefix',
        default_value='',
        description='Prefix to add to MQTT topics (optional)'
    )
    
    client_id_arg = DeclareLaunchArgument(
        'client_id',
        default_value='mqtt_ros2_bridge',
        description='MQTT client ID'
    )
    
    reconnect_interval_arg = DeclareLaunchArgument(
        'mqtt_reconnect_interval',
        default_value='5',
        description='Seconds to wait before retrying MQTT connection'
    )
    
    publish_timestamps_arg = DeclareLaunchArgument(
        'publish_timestamps',
        default_value='false',
        description='Whether to include timestamps in published messages'
    )

    # Bridge node
    mqtt_bridge_node = Node(
        package='mqtt_ros2_bridge',
        executable='mqtt_ros2_bridge_node',
        name='mqtt_ros2_bridge',
        output='screen',
        emulate_tty=True,
        parameters=[
            {
                'mqtt_broker_host': LaunchConfiguration('mqtt_host'),
                'mqtt_broker_port': LaunchConfiguration('mqtt_port'),
                'mqtt_topic_prefix': LaunchConfiguration('mqtt_topic_prefix'),
                'client_id': LaunchConfiguration('client_id'),
                'mqtt_reconnect_interval': LaunchConfiguration('mqtt_reconnect_interval'),
                'publish_timestamps': LaunchConfiguration('publish_timestamps'),
            }
        ],
    )

    return LaunchDescription([
        mqtt_host_arg,
        mqtt_port_arg,
        mqtt_prefix_arg,
        client_id_arg,
        reconnect_interval_arg,
        publish_timestamps_arg,
        mqtt_bridge_node,
    ])
