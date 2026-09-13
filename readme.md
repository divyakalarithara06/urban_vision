UrbanVision

Overview

UrbanVision is an AI-powered smart city monitoring system that uses computer vision and machine learning to improve urban management through:

Traffic monitoring and adaptive signal control
Road accident detection and alert generation
Waste detection and cleanliness monitoring

The system uses the YOLOv8 object detection framework to analyze video feeds and generate real-time insights for city authorities.

Problem Statement

Urban areas face increasing challenges such as traffic congestion, road accidents, and improper waste management. Existing systems often rely on fixed-time traffic signals, manual monitoring, or expensive external data sources. UrbanVision aims to provide an intelligent, camera-based solution capable of monitoring multiple urban challenges through a unified platform.

Objectives
Detect and count vehicles from traffic video feeds.
Estimate traffic density and recommend signal timings.
Detect road accidents and generate alerts.
Detect garbage accumulation and overflowing bins.
Provide a centralized monitoring dashboard.
Reduce dependence on external traffic APIs and satellite data.

Technology Stack
Programming Language:Python 3.10.11
AI Framework:YOLOv8 (Ultralytics 8.4.60)
Deep Learning:PyTorch 2.12.0
Computer Vision:OpenCV 4.13.0
Dashboar:Streamlit
Backend:Flask
Data Processing:NumPy,Pandas
Visualization:Matplotlib

Project Structure

urban_vision/

datasets/
models/
traffic_detection/
accident_detection/
waste_detection/
dashboard/
backend/
reports/
README.md