from setuptools import find_packages, setup
import os
from glob import glob
package_name = 'robot_control'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob(os.path.join('launch', '*launch.[pxy][yma]*'))),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='spark',
    maintainer_email='spark@todo.todo',
    description='TODO: Package description',
    license='TODO: License declaration',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'joy_to_esp32 = robot_control.joy_to_esp32:main',
            'mecanum_joy_teleop = robot_control.mecanum_joy_teleop:main',
            'websocket_telemetry = robot_control.websocket_telemetry:main',
            'websocket_telemetry_funnel = robot_control.websocket_telemetry_funnel:main',
            'audio_feedback_manager = robot_control.audio_feedback_manager:main',
        ],
    },
)
