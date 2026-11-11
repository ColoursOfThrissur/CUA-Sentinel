---
name: skill_task_dag_1794336644_84688a_step_1_telemetry
description: Auto-synthesized skill for: Generate an edge IoT device server metrics CSV dataset with 12 hourly readings including timestamp, server_id, cpu_utilization, memory_mb, and packet_loss_rate
version: 1
verified_at: 1794336818.8169942
effect_class: READ_ONLY
---
# skill_task_dag_1794336644_84688a_step_1_telemetry (v1)
Auto-synthesized skill for: Generate an edge IoT device server metrics CSV dataset with 12 hourly readings including timestamp, server_id, cpu_utilization, memory_mb, and packet_loss_rate

## Parameters
```json
{}
```

## Implementation
```python
import csv
import datetime
import random

OUTPUT_PATH = 'C:/Users/derik/Desktop/Derik/Projects/Sentinel/workspaces/task_dag_1794336644_84688a_step_1_telemetry.csv'

def generate_and_write_metrics():
    base_time = datetime.datetime.now()
    data_rows = []
    
    # Generate 12 hourly readings
    for i in range(12):
        current_time = base_time + datetime.timedelta(hours=i)
        server_id = f"edge-server-{random.randint(1, 5)}"
        cpu_utilization = round(random.uniform(0.0, 100.0), 2)
        memory_mb = round(random.uniform(512.0, 8192.0), 2)
        packet_loss_rate = round(random.uniform(0.0, 5.0), 4)
        
        data_rows.append([
            current_time.isoformat(),
            server_id,
            cpu_utilization,
            memory_mb,
            packet_loss_rate
        ])

    # Write to CSV file ensuring flush and close via context manager
    with open(OUTPUT_PATH, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['timestamp', 'server_id', 'cpu_utilization', 'memory_mb', 'packet_loss_rate'])
        writer.writerows(data_rows)

if __name__ == '__main__':
    generate_and_write_metrics()
```
