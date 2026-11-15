import csv
from datetime import datetime, timedelta
import random

def generate_timestamp(start_date):
    return start_date + timedelta(days=random.randint(0, 30), hours=random.randint(0, 23))

def generate_bearing_temp():
    return round(random.uniform(50.0, 100.0), 2)

def generate_vibration():
    return round(random.uniform(0.0, 10.0), 2)

def generate_anomaly_flag(bearing_temp, vibration):
    if bearing_temp > 90 or vibration > 8:
        return 'Yes'
    else:
        return 'No'

def generate_csv(output_path, num_rows=1000):
    with open(output_path, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(['timestamp', 'machine_id', 'bearing_temp', 'vibration', 'anomaly_flag'])

        start_date = datetime(2023, 1, 1)
        for _ in range(num_rows):
            timestamp = generate_timestamp(start_date).isoformat()
            machine_id = f'M{random.randint(1, 10)}'
            bearing_temp = generate_bearing_temp()
            vibration = generate_vibration()
            anomaly_flag = generate_anomaly_flag(bearing_temp, vibration)

            writer.writerow([timestamp, machine_id, bearing_temp, vibration, anomaly_flag])

# Generate the CSV file
generate_csv('G:/Sentinel_Workspace/task_1794672343.csv')